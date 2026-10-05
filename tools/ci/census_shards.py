"""PR-DEVEX-CENSUS-140: deterministic file-level sharding of the full deterministic census.

The full census runs the same pytest surface as before; only its execution is split. The partition is a pure
function of the repository-relative POSIX path of each active test file::

    shard = int(sha256(path).hexdigest(), 16) % shard_count

so a new test file is assigned automatically (no manifest to edit), the result is identical on Linux and Windows,
and no timing database or optimizer exists. Whole files are never split, so test-order/fixture behavior inside a file
is unchanged. Standard library only (it runs before and after the application environment exists).

Subcommands::

    plan       --shards N --index I [--out FILE]       print/write the files of one shard (pytest @argsfile)
    run-shard  --shards N --index I --out-dir DIR      run ordinary pytest for one shard, write xml/manifest/result json
    verify     --shards N --results-dir DIR            aggregate gate: partition + artifacts + exit codes + merged census
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_summary  # noqa: E402
from run_collection_gate import DEFAULT_COLLECTION_EXCLUDES  # noqa: E402

TEST_GLOB = "test_*.py"
PYTEST_ARGS = ("-q", "-rfE", "--tb=short", "--timeout=300", "-o", "junit_family=xunit2", "-o", "junit_duration_report=total")


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


def active_test_files(root: Path = ROOT, excludes: Iterable[str] = DEFAULT_COLLECTION_EXCLUDES) -> list[str]:
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
            if any(part in skip_dirs or part == "__pycache__" or part.startswith(".") for part in parts):
                continue
            posix = rel.as_posix()
            if any(posix == ex or posix.startswith(ex + "/") for ex in excluded):
                continue
            found.add(posix)
    return sorted(found)


# --- the partition -------------------------------------------------------------------------------------------------


def normalize_path(path: str | Path) -> str:
    """Repo-relative POSIX form so Windows and Linux hash the same string."""

    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def shard_of(path: str | Path, shard_count: int) -> int:
    """Stable (cross-platform, cross-process) shard index of one test file."""

    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    digest = hashlib.sha256(normalize_path(path).encode("utf-8")).hexdigest()
    return int(digest, 16) % shard_count


def partition(files: Iterable[str], shard_count: int) -> list[list[str]]:
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for file in sorted({normalize_path(f) for f in files}):
        shards[shard_of(file, shard_count)].append(file)
    return shards


def partition_problems(
    active: Iterable[str], shards: Sequence[Sequence[str]]
) -> list[str]:
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
                problems.append(f"shard {index} contains {norm}, which is outside the active census")
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

    out_dir.mkdir(parents=True, exist_ok=True)
    files = partition(active_test_files(root), shard_count)[index]
    argsfile = out_dir / f"census-shard-{index}.args"
    argsfile.write_text("\n".join(files) + "\n", encoding="utf-8")
    manifest = out_dir / f"census-shard-{index}.manifest.json"
    manifest.write_text(json.dumps({"index": index, "shards": shard_count, "files": files}, indent=1), encoding="utf-8")
    xml_path = out_dir / f"census-shard-{index}.xml"
    command = [
        sys.executable, "-m", "pytest", *pytest_args(), f"--junitxml={xml_path}", *extra_pytest_args, f"@{argsfile}",
    ]
    started = time.monotonic()
    completed = subprocess.run(command, cwd=root, check=False)
    wall = time.monotonic() - started
    (out_dir / f"census-shard-{index}.result.json").write_text(
        json.dumps({
            "index": index, "shards": shard_count, "files": len(files),
            "exit_code": completed.returncode, "pytest_wall_seconds": round(wall, 1),
        }, indent=1),
        encoding="utf-8",
    )
    return completed.returncode


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
    shard_count: int, results_dir: Path, *, root: Path = ROOT, active: Iterable[str] | None = None
) -> tuple[list[str], dict[str, Any]]:
    """Aggregate gate. Returns (problems, evidence). ``problems`` empty means the census is complete and consistent."""

    active_files = sorted(active) if active is not None else active_test_files(root)
    problems: list[str] = []
    expected = partition(active_files, shard_count)
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
        results.append(result)
        xmls.append(xml_path)
        if manifest["files"] != expected[index]:
            problems.append(f"shard {index}: executed manifest differs from the partition of the current active census")
        if result.get("exit_code") != 0:
            problems.append(f"shard {index}: pytest exited with {result.get('exit_code')}")
        stray = sorted(junit_files(xml_path) - set(manifest["files"]))
        if stray:
            problems.append(f"shard {index}: JUnit records for files outside its manifest: {stray[:5]}")

    problems += [f"manifests: {p}" for p in partition_problems(active_files, manifests)]

    evidence: dict[str, Any] = {
        "shards": shard_count, "active_files": len(active_files), "shard_results": results,
    }
    if xmls:
        merged = results_dir / "census.xml"
        merge_junit(xmls, merged)
        summary = census_summary.summarize(merged)
        walls = [r["pytest_wall_seconds"] for r in results]
        no_record = sorted(set(active_files) - junit_files(merged))
        evidence.update({
            "summary": summary,
            "parallel_wall_seconds": max(walls) if walls else None,
            "fastest_shard_wall_seconds": min(walls) if walls else None,
            "sum_shard_wall_seconds": round(sum(walls), 1),
            "imbalance_ratio": round(max(walls) / min(walls), 2) if walls and min(walls) > 0 else None,
            "files_without_junit_records": no_record,
        })
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
        lines += ["", "| shard | files | exit | pytest wall s |", "|---:|---:|---:|---:|"]
        for result in evidence["shard_results"]:
            lines.append(f"| {result['index']} | {result['files']} | {result['exit_code']} | {result['pytest_wall_seconds']} |")
        none_recorded = evidence.get("files_without_junit_records") or []
        if none_recorded:
            lines += ["", f"Active files with no JUnit record (zero collected tests): {len(none_recorded)}"]
    lines += ["", "**Census completeness gate:** " + ("PASS" if not problems else "FAIL")]
    lines += [f"- {p}" for p in problems]
    if summary:
        lines += ["", census_summary.render_markdown(summary)]
    return "\n".join(lines) + "\n"


# --- CLI -----------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    args = parser.parse_args(argv)
    if args.command == "plan":
        files = partition(active_test_files(), args.shards)[args.index]
        text = "\n".join(files) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if args.command == "run-shard":
        return run_shard(args.shards, args.index, args.out_dir, extra_pytest_args=args.pytest_args)
    problems, evidence = verify_results(args.shards, args.results_dir)
    sys.stdout.write(render_aggregate(problems, evidence))
    if args.json:
        args.json.write_text(json.dumps({"problems": problems, **evidence}, indent=1, default=str), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
