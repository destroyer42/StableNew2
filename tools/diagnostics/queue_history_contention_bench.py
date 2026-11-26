"""Micro-benchmark: queue/History projection latency against a copy-shaped job repository (PR-QUEUE-LOCK-IO-N9).

It reproduces the co-stall seen in the workstation log (a queue claim and the queue projection each taking 2-120 s
with per-job CPU near 0.1 ms) on a TEMPORARY database, never on ``state/``:

* ``--rows`` terminal filler rows shaped like the live table (``njr_snapshot`` about 15 KB, ``result_json`` about
  74 KB, ``created_at`` ascending), plus ``--queued`` real, reconstructable queued jobs at the newest end;
* phase 1 times the History refresh read (``list_recent_jobs`` for COMPLETED/FAILED, limit 20);
* phase 2 runs the queue the way the app does while it drains a batch: one worker claims, reports progress and
  completes each job; a History refresher re-reads after every completion (the GUI's ``HistoryProjectionRefresh``);
  a projection reader lists the active jobs every 20 ms (the queue panel's ``QueueProjectionRefresh`` and the Tk
  thread's queue reads). It reports claim latency and projection-reader latency.

``--commit-delay-ms`` adds a fixed sleep inside every repository commit (a busy disk's fsync), to show whether
readers of the queue projection wait for the disk.

``--src`` imports ``src`` from another checkout (for example an extracted ``origin/main``) so the same workload can be
measured before and after a change. The filler is built once per ``--db`` path and reused; queued rows are rebuilt
on every run. Nothing here touches the network, a GPU or the live ``state/`` directory.

Example::

    python tools/diagnostics/queue_history_contention_bench.py --db %TEMP%\\n9\\bench.sqlite3 --rows 55000
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

FILLER_PREFIX = "fill-"
_BASE_TIME = datetime(2026, 1, 1)


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(len(ordered) * q))]  # noqa: E731
    return {
        "n": len(ordered),
        "p50_ms": round(pick(0.50), 2),
        "p99_ms": round(pick(0.99), 2),
        "max_ms": round(ordered[-1], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
    }


def _import_src(src_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(src_root))
    import importlib

    models = importlib.import_module("src.pipeline.job_models_v2")
    job_model = importlib.import_module("src.queue.job_model")
    api: dict[str, Any] = {
        name: getattr(models, name)
        for name in (
            "CURRENT_NJR_SCHEMA_VERSION",
            "ImageWorkloadSpec",
            "NJRProvenance",
            "NormalizedJobRecord",
            "OutputPlan",
            "SourceDescriptor",
            "SourceKind",
            "StageConfig",
            "UnifiedJobSummary",
            "WorkloadKind",
        )
    }
    api["Job"], api["JobStatus"] = job_model.Job, job_model.JobStatus
    api["JobQueue"] = importlib.import_module("src.queue.job_queue").JobQueue
    api["JobRepository"] = importlib.import_module("src.queue.job_repository").JobRepository
    return api


def _make_job(api: dict[str, Any], job_id: str, prompt: str) -> Any:
    record = api["NormalizedJobRecord"](
        schema_version=api["CURRENT_NJR_SCHEMA_VERSION"],
        job_id=job_id,
        workload_kind=api["WorkloadKind"].IMAGE,
        source=api["SourceDescriptor"](kind=api["SourceKind"].CLI),
        workload=api["ImageWorkloadSpec"](
            positive_prompt=prompt,
            negative_prompt="blurry, bad quality",
            config={"model": "sdxl", "prompt": prompt, "steps": 30, "width": 1024, "height": 1024},
        ),
        stages=(
            api["StageConfig"](
                stage_type="txt2img", enabled=True, steps=30, cfg_scale=7.0, model="sdxl"
            ),
        ),
        output_plan=api["OutputPlan"](base_output_dir="output", filename_template="{seed}"),
        provenance=api["NJRProvenance"](seed=42),
    )
    job = api["Job"](job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record
    return job


def _result_payload(size: int, tag: str) -> dict[str, Any]:
    # Many small artifact entries, like a real result_json (manifests, per-stage metadata, artifact paths).
    entry = {"path": f"C:/output/Pipeline/{tag}/image.png", "stage": "txt2img", "meta": "x" * 300}
    count = max(1, size // 420)
    return {"success": True, "artifacts": [dict(entry, index=i) for i in range(count)]}


def build_filler(db: Path, rows: int, api: dict[str, Any]) -> None:
    """Create the schema with the real repository, then bulk-insert terminal rows (fast, not durable)."""

    api["JobRepository"](db).close()
    connection = sqlite3.connect(db)
    existing = connection.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_id LIKE ?", (FILLER_PREFIX + "%",)
    ).fetchone()[0]
    if existing >= rows:
        connection.close()
        return
    connection.execute("PRAGMA synchronous = OFF")
    snapshot = json.dumps({"normalized_job": {"pad": "n" * 15_000}})
    result = json.dumps(_result_payload(74_000, "filler"))
    connection.execute("BEGIN")
    for index in range(existing, rows):
        created = (_BASE_TIME + timedelta(seconds=index)).isoformat()
        status = "failed" if index % 17 == 0 else ("cancelled" if index % 23 == 0 else "completed")
        connection.execute(
            """
            INSERT INTO jobs (job_id, njr_snapshot, njr_fingerprint, priority, queue_order, status, created_at,
                queued_at, started_at, completed_at, updated_at, progress, run_mode, source, prompt_source,
                randomizer_metadata, execution_metadata, result_json, artifact_references, payload_summary)
            VALUES (?, ?, 'f', 1, ?, ?, ?, ?, ?, ?, ?, 0.0, 'queue', 'gui', 'pack', '{}', '{}', ?, '[]', 'filler')
            """,
            (
                f"{FILLER_PREFIX}{index:08d}",
                snapshot,
                index,
                status,
                created,
                created,
                created,
                created,
                created,
                result,
            ),
        )
        if index % 2000 == 1999:
            connection.execute("COMMIT")
            connection.execute("BEGIN")
    connection.execute("COMMIT")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()


def reset_queued(db: Path, queued: int, api: dict[str, Any]) -> list[str]:
    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM jobs WHERE job_id NOT LIKE ?", (FILLER_PREFIX + "%",))
    connection.commit()
    connection.close()
    repository = api["JobRepository"](db)
    jobs = [
        _make_job(api, f"bench-{index:04d}", f"benchmark prompt {index}") for index in range(queued)
    ]
    repository.record_job_submissions(jobs)
    repository.close()
    return [job.job_id for job in jobs]


def _slow_commit_repository(api: dict[str, Any], delay_s: float) -> type:
    base = api["JobRepository"]

    class SlowCommitRepository(base):  # type: ignore[misc, valid-type]
        """The real repository; every commit also waits ``delay_s`` (a busy disk's fsync)."""

        @contextmanager
        def transaction(self) -> Iterator[sqlite3.Connection]:
            with super().transaction() as connection:
                yield connection
                if delay_s > 0:
                    time.sleep(delay_s)

    return SlowCommitRepository


def measure_history(repository: Any, api: dict[str, Any], repeats: int) -> dict[str, float]:
    statuses = {api["JobStatus"].COMPLETED, api["JobStatus"].FAILED}
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        repository.list_recent_jobs(statuses=statuses, limit=20)
        timings.append((time.perf_counter() - started) * 1000)
    return _percentiles(timings)


def run_drain(
    db: Path, api: dict[str, Any], *, cycles: int, commit_delay_s: float
) -> dict[str, Any]:
    repository = _slow_commit_repository(api, commit_delay_s)(db)
    queue = api["JobQueue"](repository=repository)
    summary = api["UnifiedJobSummary"]
    statuses = {api["JobStatus"].COMPLETED, api["JobStatus"].FAILED}
    stop = threading.Event()
    completed = threading.Condition()
    completions = [0]
    claims: list[float] = []
    reads: list[float] = []
    history: list[float] = []
    errors: list[str] = []

    def guarded(fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - reported in the result, never swallowed silently
                errors.append(f"{type(exc).__name__}: {exc}")
                stop.set()

        return run

    def worker() -> None:
        result = _result_payload(74_000, "bench")
        for _ in range(cycles):
            started = time.perf_counter()
            job = queue.claim_next_job()
            claims.append((time.perf_counter() - started) * 1000)
            if job is None:
                break
            for progress in (0.25, 0.5, 0.75):
                queue.record_progress(job.job_id, progress, 5.0)
            queue.mark_completed(job.job_id, result)
            with completed:
                completions[0] += 1
                completed.notify_all()
        stop.set()
        with completed:
            completed.notify_all()

    def history_refresher() -> None:
        seen = 0
        while not stop.is_set():
            with completed:
                completed.wait_for(
                    lambda last=seen: completions[0] > last or stop.is_set(), timeout=1.0
                )
                seen = completions[0]
            if stop.is_set():
                return
            started = time.perf_counter()
            repository.list_recent_jobs(statuses=statuses, limit=20)
            history.append((time.perf_counter() - started) * 1000)

    def projection_reader() -> None:
        while not stop.is_set():
            started = time.perf_counter()
            for job in queue.list_active_jobs_ordered():
                record = getattr(job, "_normalized_record", None)
                if record is not None:
                    summary.from_normalized_record(record)
            reads.append((time.perf_counter() - started) * 1000)
            stop.wait(0.02)

    threads = [
        threading.Thread(target=guarded(fn), name=fn.__name__)
        for fn in (worker, history_refresher, projection_reader)
    ]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    repository.close()
    return {
        "cycles_completed": completions[0],
        "elapsed_s": round(elapsed, 2),
        "claim": _percentiles(claims),
        "projection_read": _percentiles(reads),
        "history_refresh": _percentiles(history),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db", type=Path, help="benchmark database path (default: a fresh temporary directory)"
    )
    parser.add_argument(
        "--rows", type=int, default=5000, help="terminal filler rows (live workstation: ~55,000)"
    )
    parser.add_argument("--queued", type=int, default=40)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--history-repeats", type=int, default=5)
    parser.add_argument("--commit-delay-ms", type=float, default=0.0)
    parser.add_argument(
        "--src",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="checkout to import src from",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)

    if args.db is not None and "state" in {part.lower() for part in args.db.resolve().parts}:
        parser.error(
            "refusing a path inside a state/ directory: the benchmark only runs on a temporary copy"
        )
    api = _import_src(args.src.resolve())
    with tempfile.TemporaryDirectory(prefix="n9-bench-") as scratch:
        db = args.db or Path(scratch) / "bench.sqlite3"
        db.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        build_filler(db, args.rows, api)
        reset_queued(db, args.queued, api)
        setup_s = time.perf_counter() - started
        repository = api["JobRepository"](db)
        history = measure_history(repository, api, args.history_repeats)
        repository.close()
        drain = run_drain(db, api, cycles=args.cycles, commit_delay_s=args.commit_delay_ms / 1000.0)
        report = {
            "src": str(args.src),
            "db_bytes": db.stat().st_size,
            "rows": args.rows,
            "queued": args.queued,
            "commit_delay_ms": args.commit_delay_ms,
            "setup_s": round(setup_s, 1),
            "history_query": history,
            "drain": drain,
        }
    if args.json:
        print(json.dumps(report))
    else:
        print(json.dumps(report, indent=2))
    return 1 if drain["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
