"""PR-DEVEX-CENSUS-140/150: deterministic file-level sharding of the full deterministic census.

The full census runs the same pytest surface as before; only its execution is split. The partition is a pure function
of ``(active test files, tools/ci/census_timings.json, shard count)``: whole files are assigned longest-processing-time
first by integer-millisecond weight (``census_weights``), so shards finish together instead of being balanced only by
file count. A new test file is assigned automatically (median weight), a missing timing file degrades to uniform
weights, a corrupt one fails closed, the result is identical on Linux and Windows, and any shard count >= 1 works.
Whole files are never split, so test-order/fixture behavior inside a file is unchanged. Standard library only (it runs
before and after the application environment exists).

Subcommands::

    plan            --shards N --index I [--out FILE]   print/write the files of one shard (pytest @argsfile)
    run-shard       --shards N --index I --out-dir DIR  run ordinary pytest for one shard, write xml/manifest/result json
    verify          --shards N --results-dir DIR        aggregate gate: partition + artifacts + exit codes + merged census
    simulate        [--max-shards N]                    predicted makespan/imbalance per shard count (no tests run)
    check-timings                                       validate the committed timing manifest and report its coverage
    refresh-timings --shards N --results-dir DIR --source TEXT [--out FILE]
                                                        rewrite the manifest from a clean, complete census run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_summary  # noqa: E402
import census_weights  # noqa: E402
from census_weights import Timings, TimingsError, normalize_path  # noqa: E402,F401
from run_collection_gate import DEFAULT_COLLECTION_EXCLUDES  # noqa: E402

TEST_GLOB = "test_*.py"
PYTEST_ARGS = (
    "-q",
    "-rfE",
    "--tb=short",
    "--timeout=300",
    "-o",
    "junit_family=xunit2",
    "-o",
    "junit_duration_report=total",
)


def pytest_args() -> list[str]:
    """The census flags; ``--timeout`` needs pytest-timeout (installed in CI, optional on a developer machine)."""

    import importlib.util

    has_timeout = importlib.util.find_spec("pytest_timeout") is not None
    return [a for a in PYTEST_ARGS if has_timeout or not a.startswith("--timeout")]


# --- the active census surface ------------------------------------------------------------------------------------


def _norecursedirs(root: Path) -> frozenset[str]:
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return frozenset(config["tool"]["pytest"]["ini_options"].get("norecursedirs", ()))


def _testpaths(root: Path) -> tuple[str, ...]:
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return tuple(config["tool"]["pytest"]["ini_options"].get("testpaths", ("tests",)))


def active_test_files(
    root: Path = ROOT, excludes: Iterable[str] = DEFAULT_COLLECTION_EXCLUDES
) -> list[str]:
    """Every default-census test file (repo-relative POSIX paths), including files that yield no runnable node.

    Mirrors pytest's own selection (``testpaths``, ``python_files = test_*.py``, ``norecursedirs`` and the
    ``--ignore`` list that ``run_collection_gate.DEFAULT_COLLECTION_EXCLUDES`` already owns) instead of defining a
    second test universe. Files whose only JUnit record is a collection-time skip are therefore still assigned.
    """

    skip_dirs = _norecursedirs(root)
    excluded = tuple(Path(e).as_posix().rstrip("/") for e in excludes)
    found: set[str] = set()
    for testpath in _testpaths(root):
        base = root / testpath
        for path in base.rglob(TEST_GLOB):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            parts = rel.parts[:-1]
            if any(
                part in skip_dirs or part == "__pycache__" or part.startswith(".") for part in parts
            ):
                continue
            posix = rel.as_posix()
            if any(posix == ex or posix.startswith(ex + "/") for ex in excluded):
                continue
            found.add(posix)
    return sorted(found)


# --- the partition -------------------------------------------------------------------------------------------------

_LOAD = (
    object()
)  # "read the timing manifest from the repository" (None means "no manifest": uniform weights)


def timings_path(root: Path = ROOT) -> Path:
    return root / census_weights.TIMINGS_RELATIVE_PATH


def partition(
    files: Iterable[str], shard_count: int, timings: Timings | None = None
) -> list[list[str]]:
    """Whole-file weighted partition (``timings=None`` means uniform weights); see ``census_weights``."""

    return census_weights.weighted_partition(files, shard_count, timings)


class CensusPlan(NamedTuple):
    """The complete, reproducible shard assignment plus what it was derived from."""

    shard_count: int
    shards: list[list[str]]
    weights_source: str  # "timings" or "uniform"
    timing_digest: str | None
    unmeasured: tuple[str, ...]
    stale: tuple[str, ...]
    predicted_ms: list[int]
    digest: str


def build_plan(
    shard_count: int,
    *,
    root: Path = ROOT,
    active: Iterable[str] | None = None,
    timings: Any = _LOAD,
) -> CensusPlan:
    """The plan every shard job and the aggregate verifier derive independently from the same checkout."""

    files = sorted(active) if active is not None else active_test_files(root)
    resolved: Timings | None = (
        census_weights.load_timings(timings_path(root)) if timings is _LOAD else timings
    )
    report = census_weights.weigh(files, resolved)
    shards = census_weights.weighted_partition(files, shard_count, resolved)
    return CensusPlan(
        shard_count=shard_count,
        shards=shards,
        weights_source="timings" if resolved is not None else "uniform",
        timing_digest=resolved.digest if resolved is not None else None,
        unmeasured=report.unmeasured,
        stale=report.stale,
        predicted_ms=census_weights.shard_loads(shards, report.weights),
        digest=census_weights.plan_digest(shards),
    )


def partition_problems(active: Iterable[str], shards: Sequence[Sequence[str]]) -> list[str]:
    """Fail-closed invariants: complete, disjoint, and nothing outside the active census."""

    problems: list[str] = []
    active_set = {normalize_path(f) for f in active}
    seen: dict[str, int] = {}
    for index, files in enumerate(shards):
        for file in files:
            norm = normalize_path(file)
            if norm in seen:
                problems.append(f"{norm} is assigned to shards {seen[norm]} and {index}")
            seen[norm] = index
            if norm not in active_set:
                problems.append(
                    f"shard {index} contains {norm}, which is outside the active census"
                )
    for file in sorted(active_set - set(seen)):
        problems.append(f"{file} is in the active census but assigned to no shard")
    return problems


# --- running one shard ---------------------------------------------------------------------------------------------


def run_shard(
    shard_count: int,
    index: int,
    out_dir: Path,
    *,
    root: Path = ROOT,
    extra_pytest_args: Sequence[str] = (),
) -> int:
    """Run ordinary pytest for one shard's whole files; always write xml, manifest and a result record."""

    check_index(shard_count, index)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(shard_count, root=root)
    files = plan.shards[index]
    argsfile = out_dir / f"census-shard-{index}.args"
    argsfile.write_text("\n".join(files) + "\n", encoding="utf-8")
    manifest = out_dir / f"census-shard-{index}.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "index": index,
                "shards": shard_count,
                "files": files,
                "plan_digest": plan.digest,
                "weights_source": plan.weights_source,
                "timing_digest": plan.timing_digest,
                "predicted_seconds": round(plan.predicted_ms[index] / 1000, 1),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    xml_path = out_dir / f"census-shard-{index}.xml"
    started = time.monotonic()
    if files:
        command = [
            sys.executable,
            "-m",
            "pytest",
            *pytest_args(),
            f"--junitxml={xml_path}",
            *extra_pytest_args,
            f"@{argsfile}",
        ]
        returncode = subprocess.run(command, cwd=root, check=False).returncode
    else:
        # More shards than active files: an empty shard must run nothing. An empty @argsfile would make pytest fall
        # back to ``testpaths`` and execute the entire suite in this shard.
        xml_path.write_text(EMPTY_JUNIT, encoding="utf-8")
        returncode = 0
    wall = time.monotonic() - started
    (out_dir / f"census-shard-{index}.result.json").write_text(
        json.dumps(
            {
                "index": index,
                "shards": shard_count,
                "files": len(files),
                "exit_code": returncode,
                "pytest_wall_seconds": round(wall, 1),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return returncode


EMPTY_JUNIT = '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="0" time="0"/></testsuites>\n'


def check_index(shard_count: int, index: int) -> None:
    """Fail closed on a nonsensical selection (a negative index would otherwise silently pick from the end)."""

    if shard_count < 1:
        raise ValueError(f"--shards must be >= 1, got {shard_count}")
    if not 0 <= index < shard_count:
        raise ValueError(f"--index must be in 0..{shard_count - 1}, got {index}")


# --- aggregation ---------------------------------------------------------------------------------------------------


def merge_junit(xml_paths: Sequence[Path], out_path: Path) -> None:
    """One synthetic JUnit (all testcases) so census_summary stays the single summarizer."""

    merged = ET.Element("testsuites")
    suite = ET.SubElement(merged, "testsuite", name="pytest-sharded-census")
    total_time = 0.0
    count = 0
    for path in xml_paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for source in suites:
            for case in source.iter("testcase"):
                suite.append(case)
                count += 1
        total_time += sum(float(s.get("time") or 0.0) for s in suites)
    suite.set("tests", str(count))
    suite.set("time", f"{total_time:.3f}")
    ET.ElementTree(merged).write(out_path, encoding="utf-8", xml_declaration=True)


def junit_files(xml_path: Path) -> set[str]:
    summary = census_summary.summarize(xml_path, top=0)
    return {row["file"] for row in summary["by_file"]}


def verify_results(
    shard_count: int,
    results_dir: Path,
    *,
    root: Path = ROOT,
    active: Iterable[str] | None = None,
    timings: Any = _LOAD,
) -> tuple[list[str], dict[str, Any]]:
    """Aggregate gate. Returns (problems, evidence). ``problems`` empty means the census is complete and consistent."""

    active_files = sorted(active) if active is not None else active_test_files(root)
    problems: list[str] = []
    try:
        plan = build_plan(shard_count, root=root, active=active_files, timings=timings)
    except (TimingsError, ValueError) as exc:
        return [f"cannot derive the shard plan: {exc}"], {
            "shards": shard_count,
            "active_files": len(active_files),
            "shard_results": [],
        }
    expected = plan.shards
    problems += partition_problems(active_files, expected)

    manifests: list[list[str]] = []
    results: list[dict[str, Any]] = []
    xmls: list[Path] = []
    for index in range(shard_count):
        manifest_path = results_dir / f"census-shard-{index}.manifest.json"
        result_path = results_dir / f"census-shard-{index}.result.json"
        xml_path = results_dir / f"census-shard-{index}.xml"
        if not (manifest_path.is_file() and result_path.is_file() and xml_path.is_file()):
            problems.append(f"shard {index}: manifest/result/xml artifact is missing")
            manifests.append([])
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        manifests.append(list(manifest["files"]))
        results.append({**result, "predicted_seconds": manifest.get("predicted_seconds")})
        xmls.append(xml_path)
        if manifest.get("index") != index or manifest.get("shards") != shard_count:
            problems.append(
                f"shard {index}: manifest identifies itself as shard {manifest.get('index')} of {manifest.get('shards')}, "
                f"expected {index} of {shard_count}"
            )
        if manifest.get("plan_digest") != plan.digest:
            problems.append(
                f"shard {index}: plan digest differs from the plan of the current tree (different checkout or timing manifest)"
            )
        if manifest["files"] != expected[index]:
            problems.append(
                f"shard {index}: executed manifest differs from the partition of the current active census"
            )
        if result.get("exit_code") != 0:
            problems.append(f"shard {index}: pytest exited with {result.get('exit_code')}")
        stray = sorted(junit_files(xml_path) - set(manifest["files"]))
        if stray:
            problems.append(
                f"shard {index}: JUnit records for files outside its manifest: {stray[:5]}"
            )

    problems += [f"manifests: {p}" for p in partition_problems(active_files, manifests)]

    evidence: dict[str, Any] = {
        "shards": shard_count,
        "active_files": len(active_files),
        "shard_results": results,
        "weights_source": plan.weights_source,
        "timing_digest": plan.timing_digest,
        "unmeasured_files": list(plan.unmeasured),
        "stale_timing_records": list(plan.stale),
        "predicted_seconds": [round(ms / 1000, 1) for ms in plan.predicted_ms],
    }
    if xmls:
        merged = results_dir / "census.xml"
        merge_junit(xmls, merged)
        summary = census_summary.summarize(merged)
        walls = [r["pytest_wall_seconds"] for r in results]
        no_record = sorted(set(active_files) - junit_files(merged))
        evidence.update(
            {
                "summary": summary,
                "parallel_wall_seconds": max(walls) if walls else None,
                "fastest_shard_wall_seconds": min(walls) if walls else None,
                "sum_shard_wall_seconds": round(sum(walls), 1),
                "imbalance_ratio": round(max(walls) / min(walls), 2)
                if walls and min(walls) > 0
                else None,
                "files_without_junit_records": no_record,
            }
        )
    return problems, evidence


def render_aggregate(problems: Sequence[str], evidence: dict[str, Any]) -> str:
    lines = ["## Sharded full census", ""]
    summary = evidence.get("summary")
    if summary:
        lines.append(
            f"{summary['collected']} JUnit records: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['errors']} errors, {summary['skipped']} skipped across {evidence['shards']} shards "
            f"({evidence['active_files']} active test files)."
        )
        lines.append(
            f"Parallel census wall (slowest shard pytest wall): **{evidence['parallel_wall_seconds']} s**; fastest "
            f"{evidence['fastest_shard_wall_seconds']} s; imbalance {evidence['imbalance_ratio']}; summed shard wall "
            f"{evidence['sum_shard_wall_seconds']} s; summed test durations {summary['sum_test_seconds']} s."
        )
        lines += [
            "",
            "| shard | files | exit | pytest wall s | predicted s |",
            "|---:|---:|---:|---:|---:|",
        ]
        for result in evidence["shard_results"]:
            lines.append(
                f"| {result['index']} | {result['files']} | {result['exit_code']} | {result['pytest_wall_seconds']} "
                f"| {result.get('predicted_seconds')} |"
            )
        unmeasured = evidence.get("unmeasured_files") or []
        stale = evidence.get("stale_timing_records") or []
        lines += [
            "",
            f"Shard weights: {evidence.get('weights_source')}; {len(unmeasured)} active files without a recorded duration "
            f"(median assumed), {len(stale)} stale timing records. Refresh with "
            "`python tools/ci/census_shards.py refresh-timings` when these grow.",
        ]
        none_recorded = evidence.get("files_without_junit_records") or []
        if none_recorded:
            lines += [
                "",
                f"Active files with no JUnit record (zero collected tests): {len(none_recorded)}",
            ]
    lines += ["", "**Census completeness gate:** " + ("PASS" if not problems else "FAIL")]
    lines += [f"- {p}" for p in problems]
    if summary:
        lines += ["", census_summary.render_markdown(summary)]
    return "\n".join(lines) + "\n"


# --- timing manifest maintenance and prediction ---------------------------------------------------------------------


def file_milliseconds(xml_path: Path) -> dict[str, int]:
    """Summed JUnit testcase time (setup and teardown included) per test file, in whole milliseconds."""

    seconds: dict[str, float] = {}
    root = ET.parse(xml_path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        for case in suite.iter("testcase"):
            file = census_summary.module_file_from_classname(
                case.get("classname") or case.get("name") or ""
            )
            seconds[file] = seconds.get(file, 0.0) + float(case.get("time") or 0.0)
    return {file: round(value * 1000) for file, value in seconds.items()}


def refresh_timings(
    shard_count: int, results_dir: Path, source: str, *, root: Path = ROOT
) -> tuple[dict[str, object] | None, list[str]]:
    """Build a new manifest from a complete, green census run; refuses (fail closed) anything else.

    Every shard artifact must exist, identify itself as shard i of ``shard_count`` and have exited 0, so a partial,
    failed or mis-sized run can never become the balance reference. Active files with no JUnit record (they collect no
    test) are recorded as 0 ms; records for files that are no longer active are dropped.
    """

    problems: list[str] = []
    measured: dict[str, int] = {}
    in_a_manifest: set[str] = set()
    for index in range(shard_count):
        manifest_path = results_dir / f"census-shard-{index}.manifest.json"
        result_path = results_dir / f"census-shard-{index}.result.json"
        xml_path = results_dir / f"census-shard-{index}.xml"
        if not (manifest_path.is_file() and result_path.is_file() and xml_path.is_file()):
            problems.append(f"shard {index}: manifest/result/xml artifact is missing")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if manifest.get("index") != index or manifest.get("shards") != shard_count:
            problems.append(
                f"shard {index}: artifact is shard {manifest.get('index')} of {manifest.get('shards')}"
            )
        if result.get("exit_code") != 0:
            problems.append(
                f"shard {index}: pytest exited with {result.get('exit_code')}; timings come only from green runs"
            )
        in_a_manifest.update(normalize_path(f) for f in manifest.get("files", ()))
        for file, millis in file_milliseconds(xml_path).items():
            measured[file] = measured.get(file, 0) + millis
    if problems:
        return None, problems
    active = active_test_files(root)
    files_ms = {file: measured.get(file, 0) for file in active if file in in_a_manifest}
    if not files_ms:
        return None, [
            "no active test file appears in the shard manifests; refusing to write an empty timing manifest"
        ]
    return census_weights.build_manifest(files_ms, source), []


def simulate(max_shards: int, *, root: Path = ROOT) -> list[dict[str, Any]]:
    """Predicted balance for shard counts 1..``max_shards`` under the committed timing manifest (no tests run)."""

    active = active_test_files(root)
    timings = census_weights.load_timings(timings_path(root))
    report = census_weights.weigh(active, timings)
    total = sum(report.weights.values())
    largest = max(report.weights.values(), default=0)
    rows = []
    for count in range(1, max_shards + 1):
        shards = census_weights.weighted_partition(active, count, timings)
        loads = census_weights.shard_loads(shards, report.weights)
        slowest = max(loads)
        floor = max(
            largest, -(-total // count)
        )  # no partition of whole files can beat max(largest file, total/N)
        rows.append(
            {
                "shards": count,
                "slowest_s": round(slowest / 1000, 1),
                "fastest_s": round(min(loads) / 1000, 1),
                "lower_bound_s": round(floor / 1000, 1),
                "vs_bound": round(slowest / floor, 3) if floor else None,
                "empty_shards": sum(1 for s in shards if not s),
            }
        )
    return rows


def render_simulation(rows: Sequence[dict[str, Any]]) -> str:
    lines = [
        "| shards | slowest s | fastest s | lower bound s | slowest / bound | empty |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r['shards']} | {r['slowest_s']} | {r['fastest_s']} | {r['lower_bound_s']} | {r['vs_bound']} | {r['empty_shards']} |"
        for r in rows
    ]
    return "\n".join(lines) + "\n"


# --- CLI -----------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--shards", type=int, required=True)
    plan.add_argument("--index", type=int, required=True)
    plan.add_argument("--out", type=Path, default=None)

    run = sub.add_parser("run-shard")
    run.add_argument("--shards", type=int, required=True)
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--out-dir", type=Path, required=True)
    run.add_argument("pytest_args", nargs="*", help="extra pytest arguments (after --)")

    verify = sub.add_parser("verify")
    verify.add_argument("--shards", type=int, required=True)
    verify.add_argument("--results-dir", type=Path, required=True)
    verify.add_argument("--json", type=Path, default=None)

    sim = sub.add_parser("simulate")
    sim.add_argument("--max-shards", type=int, default=8)

    sub.add_parser("check-timings")

    refresh = sub.add_parser("refresh-timings")
    refresh.add_argument("--shards", type=int, required=True)
    refresh.add_argument("--results-dir", type=Path, required=True)
    refresh.add_argument(
        "--source", required=True, help="where the run came from, e.g. hosted CI run <id> at <sha>"
    )
    refresh.add_argument(
        "--out", type=Path, default=None, help=f"default: {census_weights.TIMINGS_RELATIVE_PATH}"
    )

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (TimingsError, ValueError) as exc:
        sys.stderr.write(f"census_shards: {exc}\n")
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        check_index(args.shards, args.index)
        files = build_plan(args.shards).shards[args.index]
        text = "\n".join(files) + "\n" if files else ""
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if args.command == "run-shard":
        return run_shard(args.shards, args.index, args.out_dir, extra_pytest_args=args.pytest_args)
    if args.command == "simulate":
        sys.stdout.write(render_simulation(simulate(args.max_shards)))
        return 0
    if args.command == "check-timings":
        timings = census_weights.load_timings(timings_path())
        if timings is None:
            sys.stdout.write("no timing manifest: shards use uniform weights\n")
            return 1
        report = census_weights.weigh(active_test_files(), timings)
        sys.stdout.write(
            f"timing manifest valid (digest {timings.digest[:12]}, {len(timings.files)} records, source: {timings.source}); "
            f"{len(report.unmeasured)} active files unmeasured, {len(report.stale)} stale records\n"
        )
        return 0
    if args.command == "refresh-timings":
        manifest, problems = refresh_timings(args.shards, args.results_dir, args.source)
        if manifest is None:
            sys.stderr.write("refresh refused:\n" + "".join(f"- {p}\n" for p in problems))
            return 1
        out = args.out or timings_path()
        out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        sys.stdout.write(
            f"wrote {out} ({len(manifest['files'])} files, digest {str(manifest['digest'])[:12]})\n"
        )  # type: ignore[arg-type]
        return 0
    problems, evidence = verify_results(args.shards, args.results_dir)
    sys.stdout.write(render_aggregate(problems, evidence))
    if args.json:
        args.json.write_text(
            json.dumps({"problems": problems, **evidence}, indent=1, default=str), encoding="utf-8"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
