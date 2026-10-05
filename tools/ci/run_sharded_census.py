"""PR-DEVEX-CENSUS-140: run the complete deterministic census locally in parallel worker processes.

    python tools/ci/run_sharded_census.py [--workers 2] [--out-dir DIR]

Uses the exact path-hash partition of ``census_shards`` (the same one CI shards use), starts one ordinary pytest
process per shard with its own ``--basetemp``, pytest cache, JUnit and log, then runs the same completeness gate as
the hosted aggregate job and prints one census summary. Two workers is the supported default: a Windows/Tk suite
shares ports, files and process-global state, so fewer workers means less interference. Elapsed census time is the
wall time from launching the workers until the last one finishes (not the sum of worker times).

It never starts, stops, adopts or kills an external runtime; a live external A1111/Comfy that blocks runtime-transition
tests blocks them identically in a serial run and is reported as the test failures it produces.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_shards  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKERS = 2


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, check=True).stdout


def make_isolated_checkout(destination: Path) -> Path:
    """A private checkout for one worker: detached worktree of HEAD plus the current uncommitted changes.

    Hosted shards each get their own checkout; sharing one working tree between local workers lets one worker's
    writes to repository state (``state/``, ``data/``, ``output/``) trip another worker's isolation guards, so each
    local worker runs in its own tree that is content-identical to the developer's working tree.
    """

    _git("worktree", "add", "--detach", "--force", str(destination), "HEAD")
    entries = _git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    skip_next = False
    for entry in entries:
        if skip_next:  # the old name of a rename; the new name was handled
            skip_next = False
            continue
        if len(entry) < 4:
            continue
        status, name = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            skip_next = True
        source, target = ROOT / name, destination / name
        if "D" in status and not source.exists():
            if target.exists():
                target.unlink()
            continue
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return destination


def remove_isolated_checkout(path: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT, capture_output=True, check=False)


def worker_command(workers: int, index: int, out_dir: Path, *, repo: Path = ROOT) -> list[str]:
    """The isolated worker command: shared partition, unique basetemp/cache, no source or config change."""

    base = out_dir / f"worker-{index}"
    base.mkdir(parents=True, exist_ok=True)  # pytest creates --basetemp without parents
    return [
        sys.executable, str(repo / "tools" / "ci" / "census_shards.py"), "run-shard",
        "--shards", str(workers), "--index", str(index), "--out-dir", str(out_dir),
        "--", f"--basetemp={base / 'basetemp'}", "-o", f"cache_dir={base / 'cache'}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--out-dir", type=Path, default=None, help="default: a fresh temp directory")
    parser.add_argument(
        "--shared-tree", action="store_true",
        help="run all workers in this working tree (faster start, but concurrent writes to repository state can interfere)",
    )
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="stablenew-census-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"sharded census: {args.workers} workers, output {out_dir}", flush=True)

    checkouts: list[Path] = []
    if not args.shared_tree:
        for index in range(args.workers):
            checkouts.append(make_isolated_checkout(out_dir / f"worker-{index}-repo"))

    started = time.monotonic()
    processes = []
    logs = []
    for index in range(args.workers):
        repo = checkouts[index] if checkouts else ROOT
        log = (out_dir / f"worker-{index}.log").open("w", encoding="utf-8")
        logs.append(log)
        processes.append(subprocess.Popen(worker_command(args.workers, index, out_dir, repo=repo), cwd=repo, stdout=log, stderr=subprocess.STDOUT))
    exit_codes = [process.wait() for process in processes]
    wall = time.monotonic() - started
    for log in logs:
        log.close()
    for checkout in checkouts:
        remove_isolated_checkout(checkout)

    problems, evidence = census_shards.verify_results(args.workers, out_dir)
    sys.stdout.write(census_shards.render_aggregate(problems, evidence))
    print(f"Elapsed census wall (launch to last worker): {wall:.1f} s; worker exit codes {exit_codes}; logs in {out_dir}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
