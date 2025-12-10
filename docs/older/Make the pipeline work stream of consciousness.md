Reading documents
Reading documents

Thinking longer for a better answer
Thinking longer for a better answer

Analyzing repo and designing PR specifications
import json, textwrap, os, zipfile, itertools, math, sys, subprocess, types
Retrying Python execution with necessary imports
import json, os, zipfile, textwrap, math, sys, subprocess
Loading JSON file repo_inventory.json
import pathlib, json, os, textwrap, math, sys, subprocess, zipfile
Loading repository inventory file
base = "/mnt/data"
print(os.listdir(base))

['repo_inventory.json', 'StableNew-snapshot-20251206-215343.zip', 'Rewritten GUI Wishlist PR Plan_v2.5.md', 'StableNew-snapshot-20251207-083121.zip', 'PR_TEMPLATE_v2.5.md', 'LLM_Governance_Patch_v2.5.md', 'StableNew-snapshot-20251207-062811.zip', 'StableNew_Coding_and_Testing_v2.5.md', 'Randomizer_Spec_v2.5.md', 'DOCS_INDEX_v2.5.md', 'StableNew-snapshot-20251206-115227.zip', 'StableNew-snapshot-20251206-171222.zip', 'Cluster_Compute_Spec_v2.5.md', 'Learning_System_Spec_v2.5.md', 'Roadmap_v2.5.md', 'ARCHITECTURE_v2.5.md', 'Governance_v2.5.md']
Loading and inspecting repository inventory
with open(os.path.join(base, "repo_inventory.json"), "r") as f:
    inv = json.load(f)
len(inv), list(inv.keys())[:10]

(8,
 ['repo_root',
  'created_at',
  'snapshot_zip',
  'file_count',
  'total_size_bytes',
  'excludes',
  'excluded_exts',
  'files'])
Extracting snapshot details from inventory
inv["snapshot_zip"], inv["file_count"], inv["total_size_bytes"]

('C:\\Users\\rob\\projects\\StableNew\\snapshots\\StableNew-snapshot-20251206-215343.zip',
 1383,
 13499403)
Extracting contents from ZIP file
zip_path = os.path.join(base, "StableNew-snapshot-20251206-215343.zip")
extract_dir = os.path.join(base, "repo")
with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(extract_dir)
os.listdir(extract_dir)[:20]

['.coveragerc',
 '.editorconfig',
 '.gitignore',
 '.pre-commit-config.yaml',
 'AGENTS.md',
 'CHANGELOG.md',
 'custom_pack_lists.json',
 'desktop.ini',
 'package-lock.json',
 'pyproject.toml',
 'pytest.ini',
 'README.md',
 'repo_inventory.json',
 'requirements.txt',
 'StableNew.code-workspace',
 'stablenew_snapshot_and_inventory.py',
 'test_adetailer_sync.py',
 'test_core_config_controller.py',
 'test_pr032.py',
 'validate_core_config.py']
Listing source directories
os.listdir(os.path.join(extract_dir, "src"))

['app_factory.py',
 'cli.py',
 'main.py',
 '__init__.py',
 'ai',
 'api',
 'cluster',
 'config',
 'controller',
 'gui',
 'gui_v2',
 'learning',
 'pipeline',
 'queue',
 'randomizer',
 'services',
 'stablenew.egg-info',
 'state',
 'utils']
Inspecting core pipeline and queue files
os.listdir(os.path.join(extract_dir, "src", "queue")), os.listdir(os.path.join(extract_dir, "src", "pipeline"))

(['job_history_store.py',
  'job_model.py',
  'job_queue.py',
  'single_node_runner.py',
  'stub_runner.py',
  '__init__.py'],
 ['config_merger_v2.py',
  'executor.py',
  'job_builder_v2.py',
  'job_models_v2.py',
  'job_queue_v2.py',
  'last_run_store_v2_5.py',
  'payload_builder.py',
  'pipeline_runner.py',
  'randomizer_v2.py',
  'run_config.py',
  'run_plan.py',
  'stage_models.py',
  'stage_sequencer.py',
  'variant_planner.py',
  'video.py',
  '__init__.py'])
Listing job service files in services directory
os.listdir(os.path.join(extract_dir, "src", "services"))

['config_service.py', 'queue_store_v2.py']
Exploring job services and history
I’m thinking about where to place JobService and JobHistoryService—maybe in src/queue or src/services. I’ll need to look at job_history_store, job_queue, and single_node_runner to figure this out. Alright, time to dig into those to see how everything fits together!

Previewing job-related Python files
for fname in ["job_queue.py","single_node_runner.py","job_history_store.py"]:
    print("==", fname)
    with open(os.path.join(extract_dir,"src","queue",fname),"r") as f:
        print("".join(f.readlines()[:200]))

== job_queue.py
# Subsystem: Queue
# Role: Implements the in-memory job queue contract.

"""In-memory job queue with simple priority + FIFO behavior."""

from __future__ import annotations

import heapq
from threading import Lock
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_history_store import JobHistoryStore

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime


class JobQueue:
    """Thread-safe in-memory job queue."""

    def __init__(self, *, history_store: JobHistoryStore | None = None) -> None:
        self._queue: list[tuple[int, int, str]] = []
        self._jobs: Dict[str, Job] = {}
        self._counter = 0
        self._lock = Lock()
        self._history_store = history_store
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []

    def submit(self, job: Job) -> None:
        with self._lock:
            self._counter += 1
            self._jobs[job.job_id] = job
            heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._record_submission(job)

    def get_next_job(self) -> Optional[Job]:
        with self._lock:
            while self._queue:
                _, _, job_id = heapq.heappop(self._queue)
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.QUEUED:
                    return job
            return None

    def mark_running(self, job_id: str) -> None:
        self._update_status(job_id, JobStatus.RUNNING)

    def mark_completed(self, job_id: str, result: dict | None = None) -> None:
        self._update_status(job_id, JobStatus.COMPLETED, result=result)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        job = self._update_status(job_id, JobStatus.FAILED, error_message)
        if job:
            job.error_message = error_message

    def mark_cancelled(self, job_id: str, reason: str | None = None) -> Job | None:
        return self._update_status(job_id, JobStatus.CANCELLED, reason or "cancelled")

    def list_jobs(self, status_filter: JobStatus | None = None) -> List[Job]:
        with self._lock:
            if status_filter is None:
                return list(self._jobs.values())
            return [job for job in self._jobs.values() if job.status == status_filter]

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _update_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result: dict | None = None,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.mark_status(status, error_message)
            if result is not None:
                job.result = result
            ts = job.updated_at
        self._record_status(job_id, status, ts, error_message, result=result)
        self._notify_status(job, status)
        return job

    def _record_submission(self, job: Job) -> None:
        if not self._history_store:
            return
        try:
            self._history_store.record_job_submission(job)
        except Exception:
            pass

    def _record_status(
        self,
        job_id: str,
        status: JobStatus,
        ts: "datetime",
        error: str | None,
        result: dict | None,
    ) -> None:
        if not self._history_store:
            return
        try:
            self._history_store.record_status_change(job_id, status, ts, error, result=result)
        except Exception:
            pass

    def register_status_callback(
        self, callback: Callable[[Job, JobStatus], None]
    ) -> None:
        """Allow observers to react to job status changes."""
        self._status_callbacks.append(callback)

    def _notify_status(self, job: Job, status: JobStatus) -> None:
        """Notify registered callbacks about status transitions."""
        for callback in list(self._status_callbacks):
            try:
                callback(job, status)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # PR-GUI-F2: Queue Manipulation Methods
    # ------------------------------------------------------------------

    def move_up(self, job_id: str) -> bool:
        """Move a queued job up one position (higher priority).
        
        Args:
            job_id: The ID of the job to move.
            
        Returns:
            True if the job was moved, False if not found or already at top.
        """
        with self._lock:
            # Find queued jobs in order
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == 0:
                        return False  # Already at top
                    # Swap priorities with the job above
                    prev_priority, prev_counter, prev_jid = queued[i - 1]
                    # Adjust internal queue entries
                    self._swap_queue_positions(job_id, prev_jid, priority, prev_priority)
                    return True
            return False

    def move_down(self, job_id: str) -> bool:
        """Move a queued job down one position (lower priority).
        
        Args:
            job_id: The ID of the job to move.
            
        Returns:
            True if the job was moved, False if not found or already at bottom.
        """
        with self._lock:
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == len(queued) - 1:
                        return False  # Already at bottom
                    # Swap priorities with the job below
                    next_priority, next_counter, next_jid = queued[i + 1]
                    self._swap_queue_positions(job_id, next_jid, priority, next_priority)
                    return True
            return False

    def remove(self, job_id: str) -> Job | None:
        """Remove a job from the queue.
        
        Args:
            job_id: The ID of the job to remove.
            
        Returns:
            The removed Job, or None if not found.
        """
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job:
                # Remove from heap by marking as cancelled
                job.status = JobStatus.CANCELLED
                # Rebuild queue without this job
                self._queue = [
                    (p, c, jid) for (p, c, jid) in self._queue if jid != job_id
                ]
                heapq.heapify(self._queue)
            return job

    def clear(self) -> int:
        """Clear all queued jobs (not running or completed).
        
        Returns:
            The number of jobs removed.
        """

== single_node_runner.py
# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue

logger = logging.getLogger(__name__)


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    result = self.run_callable(job)
                else:
                    result = {}
                self.job_queue.mark_completed(job.job_id, result=result)
                self._notify(job, JobStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            if self.run_callable:
                result = self.run_callable(job)
            else:
                result = {}
            self.job_queue.mark_completed(job.job_id, result=result)
            self._notify(job, JobStatus.COMPLETED)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

== job_history_store.py
# Subsystem: Queue
# Role: Persists completed job history for inspection and learning.

"""Persistent history storage for queue jobs."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.queue.job_model import Job, JobStatus
from src.cluster.worker_model import WorkerId

if TYPE_CHECKING:
    from src.pipeline.run_config import RunConfig


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class JobHistoryEntry:
    job_id: str
    created_at: datetime
    status: JobStatus
    payload_summary: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    worker_id: WorkerId | None = None
    run_mode: str = "queue"
    result: Dict[str, Any] | None = None
    # PR-112: Prompt origin tracking
    prompt_source: str = "manual"  # "manual" | "pack"
    prompt_pack_id: str | None = None
    prompt_keys: List[str] | None = None

    def to_json(self) -> str:
        data = asdict(self)
        data["status"] = self.status.value
        data["run_mode"] = self.run_mode
        data["prompt_source"] = self.prompt_source
        data["prompt_pack_id"] = self.prompt_pack_id
        data["prompt_keys"] = self.prompt_keys
        for key in ("created_at", "started_at", "completed_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def from_json(line: str) -> "JobHistoryEntry":
        raw = json.loads(line)
        def _parse_ts(value: str | None) -> datetime | None:
            if not value:
                return None
            return datetime.fromisoformat(value)

        return JobHistoryEntry(
            job_id=raw["job_id"],
            created_at=_parse_ts(raw.get("created_at")) or _utcnow(),
            status=JobStatus(raw.get("status", JobStatus.QUEUED)),
            payload_summary=raw.get("payload_summary", ""),
            started_at=_parse_ts(raw.get("started_at")),
            completed_at=_parse_ts(raw.get("completed_at")),
            error_message=raw.get("error_message"),
            worker_id=raw.get("worker_id"),
            result=raw.get("result"),
            run_mode=raw.get("run_mode", "queue"),
            prompt_source=raw.get("prompt_source", "manual"),
            prompt_pack_id=raw.get("prompt_pack_id"),
            prompt_keys=raw.get("prompt_keys"),
        )


def job_history_entry_from_run_config(
    job_id: str,
    run_config: "RunConfig",
    *,
    status: JobStatus = JobStatus.QUEUED,
    payload_summary: str = "",
    created_at: datetime | None = None,
    **extra: Any,
) -> JobHistoryEntry:
    """Create a JobHistoryEntry from a RunConfig.

    Args:
        job_id: Unique identifier for the job.
        run_config: The RunConfig containing prompt source info.
        status: Initial job status.
        payload_summary: Summary text for the job.
        created_at: Creation timestamp (defaults to now).
        **extra: Additional fields to set on the entry.

    Returns:
        A JobHistoryEntry with prompt origin fields populated.
    """
    return JobHistoryEntry(
        job_id=job_id,
        created_at=created_at or _utcnow(),
        status=status,
        payload_summary=payload_summary,
        run_mode=run_config.run_mode,
        prompt_source=run_config.prompt_source.value if hasattr(run_config.prompt_source, "value") else str(run_config.prompt_source),
        prompt_pack_id=run_config.prompt_pack_id,
        prompt_keys=list(run_config.prompt_keys) if run_config.prompt_keys else None,
        **extra,
    )


class JobHistoryStore:
    """Abstract store interface."""

    def record_job_submission(self, job: Job) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: Dict[str, Any] | None = None,
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> List[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError

    def get_job(self, job_id: str) -> Optional[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError

    def save_entry(self, entry: JobHistoryEntry) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        raise NotImplementedError


class JSONLJobHistoryStore(JobHistoryStore):
    """Append-only JSONL-backed job history."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []

    def record_job_submission(self, job: Job) -> None:
        entry = JobHistoryEntry(
            job_id=job.job_id,
            created_at=job.created_at,
            status=job.status,
            payload_summary=self._summarize_job(job),
            worker_id=getattr(job, "worker_id", None),
            run_mode=getattr(job, "run_mode", "queue"),
        )
        self._append(entry)

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: Dict[str, Any] | None = None,
    ) -> None:
        current = self.get_job(job_id)
        created_at = current.created_at if current else ts
        started_at = current.started_at
        completed_at = current.completed_at
        if status == JobStatus.RUNNING:
            started_at = started_at or ts
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            completed_at = ts

        entry = JobHistoryEntry(
            job_id=job_id,
            created_at=created_at,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            payload_summary=current.payload_summary if current else "",
            error_message=error or (current.error_message if current else None),
            worker_id=current.worker_id if current else None,
            result=result if result is not None else (current.result if current else None),
            run_mode=current.run_mode if current else "queue",
        )
        self._append(entry)

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> List[JobHistoryEntry]:

Reviewing single_node_runner
I think I need to scroll through more of the single_node_runner. I must have missed something important or overlooked a part that could be helpful. Let’s go back and take a closer look to make sure I’m not missing any key details!

Displaying first 260 lines of single_node_runner.py
with open(os.path.join(extract_dir,"src","queue","single_node_runner.py"),"r") as f:
    print("".join(f.readlines()[:260]))

# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue

logger = logging.getLogger(__name__)


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    result = self.run_callable(job)
                else:
                    result = {}
                self.job_queue.mark_completed(job.job_id, result=result)
                self._notify(job, JobStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            if self.run_callable:
                result = self.run_callable(job)
            else:
                result = {}
            self.job_queue.mark_completed(job.job_id, result=result)
            self._notify(job, JobStatus.COMPLETED)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

Finding JobService location
I’m wondering where JobService should go. It could be in src/services/queue_store_v2, or maybe it's part of config_service or even in src/controller. Hmm, I think I’ll search for it to confirm the right location! Let’s see what makes the most sense.

Searching for JobService location
import glob, re, textwrap, os, pathlib, itertools, math
Searching for JobService class location
matches = []
for root,dirs,files in os.walk(os.path.join(extract_dir,"src")):
    for fn in files:
        if fn.endswith(".py"):
            path = os.path.join(root,fn)
            with open(path,"r",errors="ignore") as f:
                txt = f.read()
            if "class JobService" in txt:
                matches.append(path)
matches
['/mnt/data/repo/src/controller/job_service.py']
Searching for JobService implementation
with open(os.path.join(extract_dir,"src","controller","job_service.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

import logging

from typing import Any, Callable, Literal, Protocol

from src.controller.job_history_service import JobHistoryService
from src.queue.job_model import Job, JobStatus
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore

QueueStatus = Literal["idle", "running", "paused"]


class RunnerProtocol(Protocol):
    """Protocol for job runners (SingleNodeJobRunner, StubRunner, etc.)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def run_once(self, job: Job) -> dict | None: ...
    def cancel_current(self) -> None: ...


# Type alias for runner factory callable
RunnerFactory = Callable[[JobQueue, Callable[[Job], dict] | None], RunnerProtocol]


class JobService:
    """Bridge between JobQueue, runner, and history for higher-level orchestration.

    PR-0114C-T(x): Supports dependency injection for runner and history service:
    - runner: Direct runner instance (legacy API, for backward compat)
    - runner_factory: Factory callable to create runner (preferred for DI)
    - history_service: History service instance (can be NullHistoryService in tests)
    """

    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: RunnerProtocol | None = None,
        history_store: JobHistoryStore | None = None,
        history_service: JobHistoryService | None = None,
        *,
        runner_factory: RunnerFactory | None = None,
        run_callable: Callable[[Job], dict] | None = None,
    ) -> None:
        """Initialize JobService with queue, runner, and history dependencies.

        Args:
            job_queue: The job queue to manage.
            runner: Direct runner instance (legacy API). If None, uses runner_factory.
            history_store: Optional history store for persistence.
            history_service: Optional history service. If None and history_store
                provided, creates a default JobHistoryService.
            runner_factory: Factory to create runner. Signature:
                (job_queue, run_callable) -> RunnerProtocol.
                If both runner and runner_factory are None, creates SingleNodeJobRunner.
            run_callable: Callable to execute jobs, passed to runner/factory.
        """
        self.job_queue = job_queue
        self.history_store = history_store
        self._run_callable = run_callable

        # PR-0114C-T(x): Support runner injection via factory or direct instance
        if runner is not None:
            self.runner = runner
        elif runner_factory is not None:
            self.runner = runner_factory(job_queue, run_callable)
        else:
            # Default: create SingleNodeJobRunner (production behavior)
            self.runner = SingleNodeJobRunner(
                job_queue,
                run_callable=run_callable,
                poll_interval=0.05,
            )

        # PR-0114C-T(x): Support history service injection
        self._history_service = history_service
        if self._history_service is None and history_store is not None:
            try:
                self._history_service = JobHistoryService(job_queue, history_store)
            except Exception:
                self._history_service = None

        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.job_queue.register_status_callback(self._handle_job_status_change)

    @property
    def queue(self) -> JobQueue:
        """Alias for job_queue for controller compatibility."""
        return self.job_queue

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
            self._record_job_history(job, status)
        elif status in {JobStatus.CANCELLED, JobStatus.FAILED}:
            self._emit(self.EVENT_JOB_FAILED, job)
            if status == JobStatus.FAILED:
                self._record_job_history(job, status)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _record_job_history(self, job: Job, status: JobStatus) -> None:
        if not self._history_service:
            return
        try:
            if status == JobStatus.COMPLETED:
                self._history_service.record(job, result=job.result)
            elif status == JobStatus.FAILED:
                self._history_service.record_failure(job, error=job.error_message)
        except Exception:
            logging.debug("Failed to record job history for %s", job.job_id, exc_info=True)

    def _emit_queue_updated(self) -> None:
        jobs = self.job_queue.list_jobs()
        summaries = [format_queue_job_summary(job) for job in jobs]
        self._emit(self.EVENT_QUEUE_UPDATED, summaries)

    def _set_queue_status(self, status: QueueStatus) -> None:
        if self._queue_status != status:
            self._queue_status = status
            self._emit(self.EVENT_QUEUE_STATUS, status)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            try:
                callback(*args)
            except Exception:
                continue

Checking job_history_service
I think I need to open up the job_history_service file now. It’s likely key to what I’m working on, and I’m hoping I’ll find the details I need to move forward. Let's see what’s inside and make sure everything’s aligned!

Opening job_history_service.py file
with open(os.path.join(extract_dir,"src","controller","job_history_service.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Controller-facing service for job history and queue introspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore


@dataclass
class JobViewModel:
    job_id: str
    status: JobStatus
    created_at: str
    started_at: str | None
    completed_at: str | None
    payload_summary: str
    is_active: bool
    last_error: str | None = None
    worker_id: str | None = None


class JobHistoryService:
    """Combine live queue state with persisted history for controller/GUI consumers."""

    def __init__(
        self,
        queue: JobQueue,
        history_store: JobHistoryStore,
        job_controller: Any | None = None,
    ) -> None:
        self._queue = queue
        self._history = history_store
        self._job_controller = job_controller
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []
        try:
            self._history.register_callback(self._on_history_update)
        except Exception:
            pass

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        self._callbacks.append(callback)

    def _on_history_update(self, entry: JobHistoryEntry) -> None:
        for callback in list(self._callbacks):
            try:
                callback(entry)
            except Exception:
                continue

    def record(self, job: Job, *, result: dict | None = None) -> None:
        try:
            entry = self._build_entry(job, status=JobStatus.COMPLETED, result=result)
            self._history.save_entry(entry)
        except Exception:
            pass

    def record_failure(self, job: Job, error: str | None = None) -> None:
        try:
            entry = self._build_entry(job, status=JobStatus.FAILED, error=error)
            self._history.save_entry(entry)
        except Exception:
            pass

    def list_active_jobs(self) -> List[JobViewModel]:
        active_statuses = {JobStatus.QUEUED, JobStatus.RUNNING}
        jobs = [j for j in self._queue.list_jobs() if j.status in active_statuses]
        return [self._from_job(j) for j in jobs]

    def list_recent_jobs(self, limit: int = 50, status: JobStatus | None = None) -> List[JobViewModel]:
        history_entries = self._history.list_jobs(status=status, limit=limit)
        active_by_id = {j.job_id: j for j in self._queue.list_jobs()}
        view_models: list[JobViewModel] = []
        for entry in history_entries:
            active_job = active_by_id.get(entry.job_id)
            if active_job:
                view_models.append(self._from_job(active_job))
            else:
                view_models.append(self._from_history(entry))
        return view_models

    def get_job(self, job_id: str) -> Optional[JobViewModel]:
        active = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if active:
            return self._from_job(active)
        entry = self._history.get_job(job_id)
        if entry:
            return self._from_history(entry)
        return None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued/running job via controller."""

        vm = self.get_job(job_id)
        if vm is None:
            return False
        if vm.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        cancel = getattr(self._job_controller, "cancel_job", None)
        if callable(cancel):
            try:
                cancel(job_id)
                return True
            except Exception:
                return False
        return False

    def retry_job(self, job_id: str) -> Optional[str]:
        """Retry a completed/failed job by re-submitting its payload."""

        vm = self.get_job(job_id)
        if vm is None or vm.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return None

        original = self._queue.get_job(job_id)
        if original is None:
            return None

        submit = getattr(self._job_controller, "submit_pipeline_run", None)
        if callable(submit):
            try:
                return submit(original.payload, priority=original.priority)
            except Exception:
                return None
        return None

    def _from_job(self, job: Job) -> JobViewModel:
        is_active = job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        return JobViewModel(
            job_id=job.job_id,
            status=job.status,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            payload_summary=self._summarize(job),
            is_active=is_active,
            last_error=job.error_message,
            worker_id=getattr(job, "worker_id", None),
        )

    def _from_history(self, entry: JobHistoryEntry) -> JobViewModel:
        return JobViewModel(
            job_id=entry.job_id,
            status=entry.status,
            created_at=entry.created_at.isoformat(),
            started_at=entry.started_at.isoformat() if entry.started_at else None,
            completed_at=entry.completed_at.isoformat() if entry.completed_at else None,
            payload_summary=entry.payload_summary,
            is_active=False,
            last_error=entry.error_message,
            worker_id=entry.worker_id,
        )

    def _summarize(self, job: Job) -> str:
        cfg = getattr(job, "pipeline_config", None)
        if cfg:
            prompt = getattr(cfg, "prompt", "") or ""
            model = getattr(cfg, "model", "") or getattr(cfg, "model_name", "")
            return f"{prompt[:64]} | {model}"
        payload = getattr(job, "payload", None)
        if callable(payload):
            return "callable payload"
        return str(payload)[:80]

    def _build_entry(
        self,
        job: Job,
        *,
        status: JobStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> JobHistoryEntry:
        prompt_keys = None
        snapshot = getattr(job, "config_snapshot", None) or {}
        raw_keys = snapshot.get("prompt_keys")
        if isinstance(raw_keys, list):
            prompt_keys = raw_keys
        return JobHistoryEntry(
            job_id=job.job_id,
            created_at=job.created_at,
            status=status,
            payload_summary=self._summarize(job),
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=error or job.error_message,
            worker_id=getattr(job, "worker_id", None),
            run_mode=getattr(job, "run_mode", "queue"),
            result=result if result is not None else job.result,
            prompt_source=getattr(job, "prompt_source", "manual"),
            prompt_pack_id=getattr(job, "prompt_pack_id", None),
            prompt_keys=prompt_keys,
        )


class NullHistoryService(JobHistoryService):
    """No-op history service for tests that don't care about history.

    PR-0114C-T(x): This class provides a safe, no-op implementation of
    JobHistoryService for test fixtures that:
    - Don't need to verify history recording.
    - Want to avoid real disk I/O or store dependencies.
    - Need a lightweight history stub for controller/GUI tests.

    Production code should never use this. It is strictly for test fixtures.
    """

    def __init__(self) -> None:
        """Initialize without queue or history store dependencies."""
        # Don't call super().__init__ - we don't need real dependencies
        self._queue = None
        self._history = None
        self._job_controller = None
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        """Register callback (stored but never invoked)."""
        self._callbacks.append(callback)

    def _on_history_update(self, entry: JobHistoryEntry) -> None:
        """No-op history update handler."""
        pass

    def record(self, job: Job, *, result: dict | None = None) -> None:
        """No-op record for completed jobs."""
        pass

    def record_failure(self, job: Job, error: str | None = None) -> None:
        """No-op record for failed jobs."""
        pass

    def list_active_jobs(self) -> List[JobViewModel]:
        """Return empty list - no active jobs tracked."""
        return []

    def list_recent_jobs(self, limit: int = 50, status: JobStatus | None = None) -> List[JobViewModel]:
        """Return empty list - no history tracked."""
        return []

    def get_job(self, job_id: str) -> Optional[JobViewModel]:
        """Return None - no jobs tracked."""
        return None

    def cancel_job(self, job_id: str) -> bool:
        """Return False - cancellation not supported."""
        return False

    def retry_job(self, job_id: str) -> Optional[str]:
        """Return None - retry not supported."""
        return None

Inspecting DI in job_service
Looks like job_service already has some Dependency Injection (DI) in place, and I think I saw a reference to that earlier in PR-0114C-Tx. I’ll need to inspect the top of job_service more carefully to understand how the DI is set up and if anything needs adjusting.

Inspecting job_service code for DI usage
with open(os.path.join(extract_dir,"src","controller","job_service.py"),"r") as f:
    txt = f.read()
print(txt[:900])

"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

import logging

from typing import Any, Callable, Literal, Protocol

from src.controller.job_history_service import JobHistoryService
from src.queue.job_model import Job, JobStatus
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore

QueueStatus = Literal["idle", "running", "paused"]


class RunnerProtocol(Protocol):
    """Protocol for job runners (SingleNodeJobRunner, StubRunner, etc.)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def run_once(self, job: Job) -> dict | None: ...
    def cancel_current(self) -> None: ...


# Type alia
Reviewing constructor later
I’ll need to scroll down later to check the constructor. Seems like it's important, but I can’t get to it immediately. When I do, I’ll be able to see how everything is initialized and ensure that everything is set up as it should be.

Locating class definition in text
start = txt.index("class JobService")
print(txt[start:start+900])

class JobService:
    """Bridge between JobQueue, runner, and history for higher-level orchestration.

    PR-0114C-T(x): Supports dependency injection for runner and history service:
    - runner: Direct runner instance (legacy API, for backward compat)
    - runner_factory: Factory callable to create runner (preferred for DI)
    - history_service: History service instance (can be NullHistoryService in tests)
    """

    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: RunnerProtocol | None = None,
        history_store: JobHistoryStore | None = None,
        history_service: JobHistoryService | None = None,
        *,
        run
Extracting substring from text input
print(txt[start+900:start+1800])

ner_factory: RunnerFactory | None = None,
        run_callable: Callable[[Job], dict] | None = None,
    ) -> None:
        """Initialize JobService with queue, runner, and history dependencies.

        Args:
            job_queue: The job queue to manage.
            runner: Direct runner instance (legacy API). If None, uses runner_factory.
            history_store: Optional history store for persistence.
            history_service: Optional history service. If None and history_store
                provided, creates a default JobHistoryService.
            runner_factory: Factory to create runner. Signature:
                (job_queue, run_callable) -> RunnerProtocol.
                If both runner and runner_factory are None, creates SingleNodeJobRunner.
            run_callable: Callable to execute jobs, passed to runner/factory.
        """
        self.job_queue = job_queue
    
Breaking down the tasks for PR-A and PR-B
For PR-A, we need to focus on validating and finalizing the core run path from the controller to the pipeline runner, as well as looking into DI usage. PR-B, on the other hand, will focus on GUI wiring around the "Add to Job" button, the preview, adding to the queue, and the run-now functionality. I'll check the relevant classes, like PipelineController in src/controller/pipeline_controller.py and possibly AppController.

Reviewing pipeline controller code for core run path
with open(os.path.join(extract_dir,"src","controller","pipeline_controller.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller.

PipelineController – V2 Run Path (summary)

GUI Run buttons → AppController._start_run_v2 → PipelineController.start_pipeline
→ JobService / SingleNodeJobRunner → PipelineController._run_pipeline_job
→ run_pipeline (PipelineRunner-backed) → Executor/API → images in output_dir.
"""

from __future__ import annotations

import logging
import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord, BatchSettings, OutputSettings
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState
from src.api.client import SDWebUIClient
from src.utils import StructuredLogger

# Logger for this module
_logger = logging.getLogger(__name__)


class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
        if isinstance(overrides, dict):
            return GuiOverrides(
                prompt=str(overrides.get("prompt", "")),
                model=str(overrides.get("model", "")),
                model_name=str(overrides.get("model_name", overrides.get("model", ""))),
                vae_name=str(overrides.get("vae_name", "")),
                sampler=str(overrides.get("sampler", "")),
                width=int(overrides.get("width", 512) or 512),
                height=int(overrides.get("height", 512) or 512),
                steps=int(overrides.get("steps", 20) or 20),
                cfg_scale=float(overrides.get("cfg_scale", 7.0) or 7.0),
                resolution_preset=str(overrides.get("resolution_preset", "")),
                negative_prompt=str(overrides.get("negative_prompt", "")),
                output_dir=str(overrides.get("output_dir", "")),
                filename_pattern=str(overrides.get("filename_pattern", "")),
                image_format=str(overrides.get("image_format", "")),
                batch_size=int(overrides.get("batch_size", 1) or 1),
                seed_mode=str(overrides.get("seed_mode", "")),
                metadata=dict(overrides.get("metadata") or {}),
            )
        return GuiOverrides()

    def _extract_state_overrides(self) -> GuiOverrides:
        extractor = getattr(self.state_manager, "get_pipeline_overrides", None)
        if callable(extractor):
            try:
                result = extractor()
                # Only use if it contains actual data
                if result and isinstance(result, dict):
                    return self._coerce_overrides(result)
            except Exception:
                pass

        if hasattr(self.state_manager, "pipeline_overrides"):
            overrides = getattr(self.state_manager, "pipeline_overrides")
            # Only use pipeline_overrides if it contains actual data
            if overrides and isinstance(overrides, dict):
                try:
                    return self._coerce_overrides(overrides)
                except Exception:
                    pass

        fallback = getattr(self, "get_gui_overrides", None)
        if callable(fallback):
            try:
                return self._coerce_overrides(fallback())
            except Exception:
                pass

        return GuiOverrides()

    def get_webui_connection_state(self):
        if hasattr(self, "_webui_connection") and self._webui_connection is not None:
            return self._webui_connection.get_state()
        return None


    def _extract_metadata(self, attr_name: str) -> dict[str, Any] | None:
        value = None
        accessor = getattr(self.state_manager, attr_name, None)
        if callable(accessor):
            try:
                value = accessor()
            except Exception:
                value = None
        elif accessor is not None:
            value = accessor

        if isinstance(value, dict):
            return dict(value)
        return None

    def _build_pipeline_config_from_state(self) -> PipelineConfig:
        overrides = self._extract_state_overrides()
        learning_metadata = self._extract_metadata("learning_metadata")
        randomizer_metadata = self._extract_metadata("randomizer_metadata")

        if learning_metadata is None and self._learning_enabled:
            learning_metadata = {"learning_enabled": True}

        return self._config_assembler.build_from_gui_input(
            overrides=overrides,
            learning_metadata=learning_metadata,
            randomizer_metadata=randomizer_metadata,
        )

    # -------------------------------------------------------------------------
    # V2 Job Building via JobBuilderV2 (PR-204C)
    # -------------------------------------------------------------------------

    def _build_normalized_jobs_from_state(
        self,
        base_config: PipelineConfig | None = None,
    ) -> list[NormalizedJobRecord]:
        """Build fully-normalized jobs from current GUI/AppState.

        This is the single entrypoint for V2 job construction.
        All run entrypoints should call this helper.

        Args:
            base_config: Optional pre-built PipelineConfig.
                If None, builds from current state.

        Returns:
            List of NormalizedJobRecord instances ready for queue/preview.
        """
        # Build base config if not provided
        if base_config is None:
            try:
                base_config = self._build_pipeline_config_from_state()
            except Exception as exc:
                _logger.warning("Failed to build pipeline config: %s", exc)
                return []

        # Extract randomization plan from state if available
        randomization_plan = None
        try:
            rand_meta = self._extract_metadata("randomizer_metadata")
            if rand_meta and rand_meta.get("enabled"):
                from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
                seed_mode_str = rand_meta.get("seed_mode", "FIXED")
                try:
                    seed_mode = RandomizationSeedMode[seed_mode_str.upper()]
                except (KeyError, AttributeError):
                    seed_mode = RandomizationSeedMode.FIXED

                randomization_plan = RandomizationPlanV2(
                    enabled=True,
                    model_choices=rand_meta.get("model_choices", []),
                    sampler_choices=rand_meta.get("sampler_choices", []),
                    cfg_scale_values=rand_meta.get("cfg_scale_values", []),
                    steps_values=rand_meta.get("steps_values", []),
                    seed_mode=seed_mode,
                    base_seed=rand_meta.get("base_seed"),
                    max_variants=rand_meta.get("max_variants", 0),
                )
        except Exception as exc:
            _logger.debug("Could not extract randomization plan: %s", exc)

        # Extract batch settings from state
        batch_settings = BatchSettings()
        try:
            overrides = self._extract_state_overrides()
            batch_size = getattr(overrides, "batch_size", 1) or 1
            batch_runs = getattr(self.state_manager, "batch_runs", 1) or 1
            batch_settings = BatchSettings(batch_size=batch_size, batch_runs=batch_runs)
        except Exception as exc:
            _logger.debug("Could not extract batch settings: %s", exc)

        # Extract output settings from state
        output_settings = OutputSettings()
        try:
            overrides = self._extract_state_overrides()
            output_dir = getattr(overrides, "output_dir", "") or "output"
            filename_pattern = getattr(overrides, "filename_pattern", "") or "{seed}"
            output_settings = OutputSettings(
                base_output_dir=output_dir,
                filename_template=filename_pattern,
            )
        except Exception as exc:
            _logger.debug("Could not extract output settings: %s", exc)

        # Build jobs via JobBuilderV2
        try:

Reviewing pipeline controller class code
# show around start_pipeline
with open(os.path.join(extract_dir,"src","controller","pipeline_controller.py"),"r") as f:
    txt_pc = f.read()
idx = txt_pc.index("class PipelineController")
print(txt_pc[idx:idx+1200])

class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(confi
Investigating start_pipeline or public methods
I need to identify where the start_pipeline function or other public methods are defined. This will help me understand how to trigger the pipeline process or interact with it properly. I should check for their locations and usage across the codebase to determine the right approach.

Identifying public methods in code
for name in ["start_pipeline","run_pipeline","start_preview_run","submit_preview_jobs_to_queue"]:
    if name in txt_pc:
        print("==",name,"==", txt_pc[txt_pc.index(name)-80:txt_pc.index(name)+260])

== start_pipeline == h (summary)

GUI Run buttons → AppController._start_run_v2 → PipelineController.start_pipeline
→ JobService / SingleNodeJobRunner → PipelineController._run_pipeline_job
→ run_pipeline (PipelineRunner-backed) → Executor/API → images in output_dir.
"""

from __future__ import annotations

import logging
import uuid

from typing import Calla
== run_pipeline == troller.start_pipeline
→ JobService / SingleNodeJobRunner → PipelineController._run_pipeline_job
→ run_pipeline (PipelineRunner-backed) → Executor/API → images in output_dir.
"""

from __future__ import annotations

import logging
import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui
== submit_preview_jobs_to_queue == result.to_dict() if hasattr(result, 'to_dict') else {"result": result}

    def submit_preview_jobs_to_queue(
        self,
        *,
        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data."""
        normalized_jobs = self.get_preview_jo
Extracting start_pipeline and public methods
print(txt_pc[txt_pc.index("def start_pipeline"):txt_pc.index("def run_pipeline")])

tate is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        # Resolve run mode
        if run_mode is None:
            try:
                pipeline_state = getattr(self.state_manager, "pipeline_state", None)
                if pipeline_state:
                    run_mode = self._normalize_run_mode(pipeline_state)
                else:
                    run_mode = "queue"
            except Exception:
                run_mode = "queue"

        # Build normalized jobs
        try:
            normalized_jobs = self._build_normalized_jobs_from_state()
        except Exception as exc:
            _logger.error("Failed to build normalized jobs: %s", exc)
            if on_error:
                on_error(exc)
            return False

        if not normalized_jobs:
            _logger.warning("No jobs to submit")
            return False

        # Convert and submit each job
        submitted_count = 0
        for record in normalized_jobs:
            try:
                job = self._to_queue_job(
                    record,
                    run_mode=run_mode,
                    source=source,
                    prompt_source=prompt_source,
                    prompt_pack_id=prompt_pack_id,
                )
                # Attach payload for execution
                job.payload = lambda j=job: self._run_job(j)

                self._job_service.submit_job_with_run_mode(job)
                submitted_count += 1
            except Exception as exc:
                _logger.error("Failed to submit job %s: %s", record.job_id, exc)
                if on_error:
                    on_error(exc)

        if submitted_count > 0:
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass
            _logger.info("Submitted %d jobs via V2 pipeline", submitted_count)
            return True

        return False

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path
        from src.learning.model_profiles import find_model_profile_for_checkpoint, find_lora_profile_for_name, suggest_preset_for
        # Resolve checkpoint path (stub: assumes models are in 'models/' dir)
        checkpoint_path = Path("models") / f"{base_model_name}.ckpt"
        model_profile = find_model_profile_for_checkpoint(checkpoint_path)
        lora_search_paths = [Path("loras")]
        lora_profiles = [find_lora_profile_for_name(name, lora_search_paths) for name in lora_names]
        lora_profiles = [lp for lp in lora_profiles if lp]
        suggested = suggest_preset_for(model_profile, lora_profiles)
        # Start from default config
        config = self.get_default_config() if hasattr(self, "get_default_config") else {}
        # Always ensure txt2img key exists and populate with defaults if missing
        if "txt2img" not in config:
            config["txt2img"] = {
                "sampler_name": "Euler",
                "scheduler": None,
                "steps": 20,
                "cfg_scale": 5.0,
                "width": 512,
                "height": 512,
                "loras": [],
            }
        # Apply suggested preset if available
        if suggested:
            config["txt2img"].update({
                "sampler_name": suggested.sampler,
                "scheduler": suggested.scheduler,
                "steps": suggested.steps,
                "cfg_scale": suggested.cfg,
                "width": suggested.resolution[0],
                "height": suggested.resolution[1],
            })
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)} for name in lora_names
            ]
            import logging
            logging.info(f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}.")
        # Apply user overrides last
        for k, v in user_overrides.items():
            # Map common override keys to txt2img
            if k in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "loras"):
                config["txt2img"][k] = v
            elif k == "cfg":
                config["txt2img"]["cfg_scale"] = v
            elif k == "resolution" and isinstance(v, (tuple, list)) and len(v) == 2:
                config["txt2img"]["width"] = v[0]
                config["txt2img"]["height"] = v[1]
            else:
                config[k] = v
        return config

    """Provide a default StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        job_builder: JobBuilderV2 | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_assembler = config_assembler if config_assembler is not None else PipelineConfigAssembler()
        self._job_builder = job_builder if job_builder is not None else JobBuilderV2()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
                pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        history_service = self.get_job_history_service()
        self._job_service = (
            job_service
            if job_service is not None
            else JobService(queue, runner, history_store, history_service=history_service)
        )
        self._job_controller.set_status_callback("pipeline", self._on_job_status)

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_learning_runner_for_tests(self):
        """Return the learning runner instance for test inspection."""

        return self._get_learning_runner()

    def handle_learning_record(self, record: LearningRecord) -> None:
        """Handle learning records forwarded from pipeline runner."""

        self._last_learning_record = record
        if self._learning_record_writer and self._learning_enabled:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass

    def get_learning_record_handler(self):
        """Return a callback suitable for passing to PipelineRunner."""

        return self.handle_learning_record

    def get_last_learning_record(self) -> LearningRecord | None:
        """Return the most recent LearningRecord handled by the controller."""

        return self._last_learning_record

    def set_learning_enabled(self, enabled: bool) -> None:
        """Enable or disable passive learning record emission."""

        self._learning_enabled = bool(enabled)

    def is_learning_enabled(self) -> bool:
        """Return whether learning record emission is enabled."""

        return self._learning_enabled

    def record_run_result(self, result: PipelineRunResult) -> None:
        """Record the last PipelineRunResult for inspection by higher layers/tests."""

        self._last_run_result = result
        self._last_stage_events = getattr(result, "stage_events", None)

    def get_last_run_result(self) -> PipelineRunResult | None:
        """Return the most recent PipelineRunResult recorded on this controller."""

        return self._last_run_result

    def validate_stage_plan(self, config: dict) -> StageExecutionPlan:
        """Build and store a stage execution plan for testing/inspection."""

        plan = build_stage_execution_plan(config)
        self._last_stage_execution_plan = plan
        return plan

    def get_last_stage_execution_plan_for_tests(self) -> StageExecutionPlan | None:
        """Return the most recent StageExecutionPlan built by this controller."""

        return self._last_stage_execution_plan

    def get_last_run_config_for_tests(self) -> dict[str, Any] | None:
        return self._last_run_config

    def get_last_stage_events_for_tests(self) -> list[dict] | None:
        """Return last emitted stage events."""

        return self._last_stage_events

    # Queue-backed execution -------------------------------------------------
    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
        *,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> bool:
        """Submit a pipeline job using assembler-enforced config."""
        if not self.state_manager.can_run():
            return False

        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        if run_config is not None:
            self._last_run_config = run_config
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            try:
                if requested_mode in {"direct", "queue"}:
                    self.state_manager.pipeline_state.run_mode = requested_mode
            except Exception:
                pass

        try:
            config = self._build_pipeline_config_from_state()
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(exc)
            raise

        def _payload() -> dict[Any, Any]:
            try:
                result: dict[str, Any] = {"config": config}
                run_result = self._run_pipeline_job(config, pipeline_func=pipeline_func)
                if isinstance(run_result, dict):
                    result.update(run_result)
                if on_complete:
                    on_complete(result)
                return result
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(exc)
                raise

        if self._queue_execution_enabled and self._queue_execution_controller:
            self._active_job_id = self._queue_execution_controller.submit_pipeline_job(_payload)
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass
            return True

        self._active_job_id = self._job_controller.submit_pipeline_run(_payload)
        try:
            self.state_manager.transition_to(GUIState.RUNNING)
        except Exception:
            pass
        return True

    def _run_pipeline_job(
        self,
        config: PipelineConfig,
        *,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a pipeline job using the assembled config or a compatibility callable.

        Priority:
        1. Legacy `run_full_pipeline` hook (if provided).
        2. Explicit `pipeline_func` callable (tests/compat).
        3. Default: use this controller's `run_pipeline` (PipelineRunner-backed).
        """

        # 1) Legacy compatibility hook (used by older harnesses/tests)
        runner = getattr(self, "run_full_pipeline", None)
        if callable(runner):
            maybe_result = runner(config)
            if isinstance(maybe_result, dict):
                return maybe_result

        # 2) Explicit pipeline callable (primarily for tests)
        if pipeline_func:
            maybe_result = pipeline_func()
            if isinstance(maybe_result, dict):
                return maybe_result

        # 3) Default path: run via PipelineRunner through this controller
        try:
            run_result = self.run_pipeline(config)
        except Exception as exc:  # noqa: BLE001
            # Surface error in a structured way so JobQueue/GUI can display it.
            return {"error": str(exc)}

        # Normalize result into a dict payload for JobQueue/history.
        if hasattr(run_result, "to_dict"):
            return {"result": run_result.to_dict()}
        if isinstance(run_result, dict):
            return run_result
        return {"result": run_result}

    def stop_pipeline(self) -> bool:
        """Cancel the active job."""

        if self._active_job_id:
            if self._queue_execution_enabled and self._queue_execution_controller:
                try:
                    self._queue_execution_controller.cancel_job(self._active_job_id)
                except Exception:
                    pass
            else:
                self._job_controller.cancel_job(self._active_job_id)
            self._active_job_id = None
            try:
                self.state_manager.transition_to(GUIState.STOPPING)
            except Exception:
                pass
            return True
        return False

    def _execute_job(self, job: Any) -> dict[Any, Any]:
        if hasattr(job, "payload") and callable(job.payload):
            result = job.payload()
            if isinstance(result, dict):
                return result
            return {}
        return {}

    def _on_job_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(job.job_id, status)

    def _on_queue_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(getattr(job, "job_id", None), status)

    def _handle_status(self, job_id: str | None, status: JobStatus) -> None:
        if job_id is None or job_id != self._active_job_id:
            return
        if status == JobStatus.COMPLETED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.FAILED:
            try:
                self.state_manager.transition_to(GUIState.ERROR)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.CANCELLED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass

    def submit_run_plan(
        self,
        run_plan: RunPlan,
        pipeline_state: PipelineState,
        app_state: Any,
    ) -> None:
        """Submit jobs from a RunPlan to the executor."""
        if not run_plan.jobs:
            self._log("RunPlan has no jobs to submit", "WARNING")
            return

        for planned_job in run_plan.jobs:
            # Build PipelineConfig for this job
            config = self._config_assembler.build_from_gui_input(
                overrides=GuiOverrides(prompt=planned_job.prompt_text),
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
            )

            # Create Job
            from src.queue.job_model import Job, JobPriority
            run_mode = self._normalize_run_mode(pipeline_state)
            job = Job(
                job_id=str(uuid.uuid4()),
                pipeline_config=config,
                priority=JobPriority.NORMAL,
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
                run_mode=run_mode,
            )
            job.payload = lambda job=job: self._run_job(job)

            self._job_service.submit_job_with_run_mode(job)

    def _run_job(self, job: Job) -> dict[str, Any]:
        """Run a single job."""
        if not job.pipeline_config:
            return {"error": "No pipeline config"}
        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        structured_logger = StructuredLogger()
        runner = PipelineRunner(api_client, structured_logger)
        result = runner.run(job.pipeline_config, self.cancel_token)
        return result.to_dict() if hasattr(result, 'to_dict') else {"result": result}

    def submit_preview_jobs_to_queue(
        self,
        *,
        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data."""
        normalized_jobs = self.get_preview_jobs()
        if not normalized_jobs:
            return 0

        submitted = 0
        for record in normalized_jobs:
            prompt_pack_id = None
            config = record.config
            if isinstance(config, dict):
                prompt_pack_id = config.get("prompt_pack_id")
            job = self._to_queue_job(
                record,
                run_mode="queue",
                source=source,
                prompt_source=prompt_source,
                prompt_pack_id=prompt_pack_id,
            )
            job.payload = lambda j=job: self._run_job(j)
            self._job_service.submit_job_with_run_mode(job)
            submitted += 1
        return submitted

    
Reviewing start_pipeline details
It seems like I truncated the starting portion of start_pipeline. I think it would be helpful to look at a larger chunk of the code—this way, I can get a better view of the function’s context and make sure I’m not missing anything important in the process.

Printing larger chunk of text from start_pipeline
start_idx = txt_pc.index("def start_pipeline")
print(txt_pc[start_idx:start_idx+1400])

def start_pipeline_v2(
        self,
        *,
        run_mode: str | None = None,
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Start pipeline using V2 job building via JobBuilderV2.

        This is the new V2 run entrypoint that:
        1. Builds normalized jobs via JobBuilderV2
        2. Converts them to queue Jobs
        3. Submits via JobService respecting run_mode

        Args:
            run_mode: Force "direct" or "queue". If None, uses state.
            source: Job source for provenance (e.g., "gui", "api").
            prompt_source: Prompt source type (e.g., "manual", "pack").
            prompt_pack_id: Optional prompt pack ID if using packs.
            on_complete: Callback on successful completion.
            on_error: Callback on error.

        Returns:
            True if jobs were submitted, False otherwise.
        """
        if not self.state_manager.can_run():
            return False

        # Check WebUI connection
        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
             
Looking into pipeline versions
I noticed that start_pipeline_v2 is the function available, not start_pipeline. Maybe start_pipeline is a wrapper for an older version of the function. I’ll need to focus on run_pipeline to get a clearer idea of how things are running now. Let's check that next.

Identifying run_pipeline function location
run_idx = txt_pc.index("def run_pipeline")
print(txt_pc[run_idx:run_idx+1200])

def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            result = runner.run(config, self.cancel_token)
        self.record_run_result(result)
        return result

    def get_job_history_service(self) -> JobHistoryService | None:
        """Return a JobHistoryService bound to this controller's queue/history."""

        if self._job_history_service is None:
            try:
                queue = self._job_controller.get_queue()
                history = self._job_controller.get_history_store()
                self._job_history_service = JobHistoryService(queue, history, job_controller=self._job_controller)
            except Exception:
                pass
        return self._job_history_service

Looking into GUI job wiring
For the GUI job wiring, I need to focus on pipeline_panel_v2 and potentially app_controller. These seem relevant for understanding how the job wiring happens on the GUI side. I'll check both to make sure things are hooked properly and aligned with the current pipeline setup.

Inspecting pipeline panel GUI code
with open(os.path.join(extract_dir,"src","gui_v2","pipeline_panel_v2.py"),"r") as f:
    print("".join(f.readlines()[:260]))

---------------------------------------------------------------------------
FileNotFoundError                         Traceback (most recent call last)
Cell In[25], line 1
----> 1 with open(os.path.join(extract_dir,"src","gui_v2","pipeline_panel_v2.py"),"r") as f:
      2     print("".join(f.readlines()[:260]))

File ~/.local/lib/python3.11/site-packages/IPython/core/interactiveshell.py:343, in _modified_open(file, *args, **kwargs)
    336 if file in {0, 1, 2}:
    337     raise ValueError(
    338         f"IPython won't let you open fd={file} by default "
    339         "as it is likely to crash IPython. If you know what you are doing, "
    340         "you can use builtins' open."
    341     )
--> 343 return io_open(file, *args, **kwargs)

FileNotFoundError: [Errno 2] No such file or directory: '/mnt/data/repo/src/gui_v2/pipeline_panel_v2.py'
Clarifying file path for the GUI panel
Ah, the path should be src/gui, not gui_v2. I had initially mixed up the two terms ('gui' and 'gui_v2'), but the panel file is definitely under src/gui. I'll list the relevant files and make sure everything aligns properly with this path.

Listing files in src/gui and src/gui_v2
os.listdir(os.path.join(extract_dir,"src","gui")), os.listdir(os.path.join(extract_dir,"src","gui_v2"))

(['adetailer_config_panel.py',
  'advanced_prompt_editor.py',
  'api_status_panel.py',
  'app_layout_v2.py',
  'app_state_v2.py',
  'center_panel.py',
  'config_panel.py',
  'controller.py',
  'core_config_panel_v2.py',
  'design_system_v2.py',
  'dropdown_loader_v2.py',
  'engine_settings_dialog.py',
  'enhanced_slider.py',
  'gui_invoker.py',
  'job_history_panel_v2.py',
  'layout_v2.py',
  'learning_review_dialog_v2.py',
  'learning_state.py',
  'log_panel.py',
  'log_trace_panel_v2.py',
  'main_window.py',
  'main_window_v2.py',
  'model_list_adapter_v2.py',
  'model_manager_panel_v2.py',
  'negative_prompt_panel_v2.py',
  'output_settings_panel_v2.py',
  'pipeline_command_bar_v2.py',
  'pipeline_controls_panel.py',
  'pipeline_panel_v2.py',
  'preview_panel_v2.py',
  'prompt_pack_adapter_v2.py',
  'prompt_pack_list_manager.py',
  'prompt_pack_panel.py',
  'prompt_pack_panel_v2.py',
  'prompt_workspace_state.py',
  'randomizer_panel_v2.py',
  'resolution_panel_v2.py',
  'scrolling.py',
  'sidebar_panel_v2.py',
  'stage_chooser.py',
  'state.py',
  'status_bar_v2.py',
  'theme.py',
  'theme_v2.py',
  'tooltip.py',
  'zone_map_v2.py',
  '__init__.py',
  'controllers',
  'models',
  'panels_v2',
  'stage_cards_v2',
  'utils',
  'views',
  'widgets'],
 ['adapters', 'validation'])
Identifying pipeline panel location
The pipeline panel is likely located in the panels_v2 directory. I'll want to check and confirm this to make sure everything is in the right spot before moving forward. It’s crucial I don’t miss this, as this might affect how the GUI works with the pipeline.

Listing files in panels_v2 directory
os.listdir(os.path.join(extract_dir,"src","gui","panels_v2"))[:40]

['layout_manager_v2.py',
 'pipeline_config_panel_v2.py',
 'pipeline_panel_v2.py',
 'pipeline_run_controls_v2.py',
 'preview_panel_v2.py',
 'queue_panel_v2.py',
 'randomizer_panel_v2.py',
 'running_job_panel_v2.py',
 'sidebar_panel_v2.py',
 'status_bar_v2.py',
 '__init__.py']
Reading pipeline panel from panels_v2
with open(os.path.join(extract_dir,"src","gui","panels_v2","pipeline_panel_v2.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Re-export of PipelinePanelV2 for modular layout use."""

from src.gui.pipeline_panel_v2 import PipelinePanelV2

__all__ = ["PipelinePanelV2"]

Confirming pipeline panel location
The actual implementation seems to be located under src/gui/pipeline_panel_v2.py, which we saw referenced in the job_service import. This makes sense since it matches the earlier clues. Now I can focus on how that integrates into the overall structure and proceed with checking for any necessary adjustments.

Reading pipeline_panel_v2.py implementation
with open(os.path.join(extract_dir,"src","gui","pipeline_panel_v2.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Pipeline panel composed of modular stage cards."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as theme_mod
from src.queue.job_model import Job
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
from src.gui.stage_cards_v2.validation_result import ValidationResult
from .widgets.scrollable_frame_v2 import ScrollableFrame


class PipelinePanelV2(ttk.Frame):
    """Container for pipeline stage cards."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: object = None,
        app_state: object = None,
        theme: object = None,
        config_manager: object = None,
        **kwargs,
    ) -> None:
        # Default sidebar attribute to avoid attribute errors
        self.sidebar: object | None = None
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self.config_manager = config_manager

        header_style = getattr(theme, "PIPELINE_HEADING_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        ttk.Label(self, text="Pipeline", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        # Prompt text widget
        self.prompt_text: tk.Text = tk.Text(self, height=4, width=60)
        self.prompt_text.pack(fill=tk.X, padx=4, pady=(0, 8))

        # Editor button
        self.open_editor_button: ttk.Button = ttk.Button(self, text="Edit Prompt", command=self._open_editor)
        self.open_editor_button.pack(anchor=tk.W, padx=4, pady=(0, 8))

        # Scrollable frame placeholder
        self._scroll: ScrollableFrame = ScrollableFrame(self)
        self.body = self._scroll.inner

        # Editor state
        self._editor: object | None = None
        self._editor_window: tk.Toplevel | None = None

        # Stage cards (parented under scrollable inner frame)
        self.txt2img_card: AdvancedTxt2ImgStageCardV2 = AdvancedTxt2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.img2img_card: AdvancedImg2ImgStageCardV2 = AdvancedImg2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card: ADetailerStageCardV2 = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.upscale_card: AdvancedUpscaleStageCardV2 = AdvancedUpscaleStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card: ADetailerStageCardV2 = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)

        self.run_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None

        self._apply_stage_visibility()

    def get_prompt(self) -> str:
        return self.prompt_text.get("1.0", tk.END).strip()

    def set_prompt(self, text: str) -> None:
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", text)
        # If there is a config or state object, update it here as well (if needed)

    class PromptEditor:
        def __init__(self, window: tk.Toplevel, initial_text: str) -> None:
            self.prompt_text: tk.Text = tk.Text(window, height=8, width=60)
            self.prompt_text.pack(fill=tk.BOTH, padx=8, pady=8)
            self.prompt_text.insert("1.0", initial_text)
            self.apply_button: ttk.Button = ttk.Button(window, text="Apply")
            self.apply_button.pack(pady=(0, 8))

    def _open_editor(self) -> None:
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.lift()
            return
        self._editor_window = tk.Toplevel(self)
        self._editor_window.title("Edit Prompt")
        self._editor = self.PromptEditor(self._editor_window, self.get_prompt())
        self._editor.apply_button.config(command=self._apply_editor_prompt)

    def _apply_editor_prompt(self) -> None:
        if self._editor and hasattr(self._editor, "prompt_text"):
            new_text = self._editor.prompt_text.get("1.0", tk.END).strip()
            self.set_prompt(new_text)
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.destroy()

    def load_from_config(self, config: dict[str, object] | None) -> None:
        data = config or {}
        self.txt2img_card.load_from_config(data)
        self.img2img_card.load_from_config(data)
        self.upscale_card.load_from_config(data)

    def to_config_delta(self) -> dict[str, dict[str, object]]:
        delta: dict[str, dict[str, object]] = {}
        for card in (self.txt2img_card, self.img2img_card, self.upscale_card):
            section_delta = card.to_config_dict()
            for section, values in section_delta.items():
                if not values:
                    continue
                delta.setdefault(section, {}).update(values)
        return delta

    def get_txt2img_form_view(self) -> dict[str, object]:
        return self.txt2img_card.to_config_dict().get("txt2img", {})

    def validate_txt2img(self) -> ValidationResult:
        return self.txt2img_card.validate()

    def set_txt2img_change_callback(self, callback: object) -> None:
        self._txt2img_change_callback = callback

    def _handle_txt2img_change(self) -> None:
        if self._txt2img_change_callback:
            self._txt2img_change_callback()

    def validate_full_pipeline(self) -> ValidationResult:
        for card in (self.txt2img_card, self.img2img_card, self.upscale_card):
            result = card.validate()
            if not result.ok:
                return result
        return ValidationResult(True, None)

    def _apply_stage_visibility(self) -> None:
        enabled = set(self.sidebar.get_enabled_stages()) if getattr(self, "sidebar", None) else {"txt2img", "img2img", "adetailer", "upscale"}
        if "txt2img" in enabled:
            self.txt2img_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.txt2img_card.pack_forget()
        if "img2img" in enabled:
            self.img2img_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.img2img_card.pack_forget()
        if "adetailer" in enabled:
            self.adetailer_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.adetailer_card.pack_forget()
        if "upscale" in enabled:
            self.upscale_card.pack(fill=tk.BOTH, expand=True)
        else:
            self.upscale_card.pack_forget()

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_controls(self.sidebar)
        except Exception:
            pass


def format_queue_job_summary(job: Job) -> str:
    result = job.result or {}
    if isinstance(result, dict) and result.get("mode") == "prompt_pack_batch":
        entries = result.get("results") or []
        total_entries = result.get("total_entries", len(entries))
        first_prompt = ""
        if entries:
            first_prompt = (entries[0].get("prompt") or "").strip()
        summary = f"{total_entries} entries"
        if first_prompt:
            snippet = first_prompt if len(first_prompt) <= 60 else first_prompt[:60] + "…"
            summary += f" | {snippet}"
        return summary
    return job.summary()


__all__ = ["PipelinePanelV2", "format_queue_job_summary"]

Inspecting preview panel for job wiring
I need to take a look at the preview panel to understand how the GUI job wiring works. This will help me trace the flow and ensure everything's connected properly. It should give a clearer picture of how each component is interacting in the interface.

Inspecting preview panel GUI code
with open(os.path.join(extract_dir,"src","gui","panels_v2","preview_panel_v2.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Re-export of PreviewPanelV2 for modular layout use."""

from src.gui.preview_panel_v2 import PreviewPanelV2

__all__ = ["PreviewPanelV2"]

Inspecting preview panel GUI code
with open(os.path.join(extract_dir,"src","gui","preview_panel_v2.py"),"r") as f:
    print("".join(f.readlines()[:400]))

"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.pipeline.job_models_v2 import JobUiSummary, NormalizedJobRecord
from src.gui.design_system_v2 import DANGER_BUTTON
from src.gui.theme_v2 import (
    BACKGROUND_ELEVATED,
    PADDING_MD,
    PRIMARY_BUTTON_STYLE,
    SECONDARY_BUTTON_STYLE,
    STATUS_LABEL_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
    TEXT_PRIMARY,
)


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self._job_summaries: list[JobUiSummary] = []

        header_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        header_frame.pack(fill="x", pady=(0, 4))

        self.header_label = ttk.Label(header_frame, text="Preview", style=STATUS_STRONG_LABEL_STYLE)
        self.header_label.pack(side=tk.LEFT)

        self.details_button = ttk.Button(
            header_frame,
            text="Details",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_details_clicked,
        )
        self.details_button.pack(side=tk.RIGHT)

        self.body = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.job_count_label = ttk.Label(self.body, text="No job selected", style=STATUS_LABEL_STYLE)
        self.job_count_label.pack(anchor=tk.W, pady=(0, 4))

        self.prompt_label = ttk.Label(self.body, text="Prompt (+)", style=STATUS_LABEL_STYLE)
        self.prompt_label.pack(anchor=tk.W)
        self.prompt_text = tk.Text(
            self.body,
            height=3,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.prompt_text.pack(fill=tk.X, pady=(0, 4))

        self.negative_prompt_label = ttk.Label(self.body, text="Prompt (–)", style=STATUS_LABEL_STYLE)
        self.negative_prompt_label.pack(anchor=tk.W)
        self.negative_prompt_text = tk.Text(
            self.body,
            height=2,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.negative_prompt_text.pack(fill=tk.X, pady=(0, 8))

        settings_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        settings_frame.pack(fill=tk.X, pady=(0, 4))
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        self.model_label = ttk.Label(settings_frame, text="Model: -", style=STATUS_LABEL_STYLE)
        self.model_label.grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.sampler_label = ttk.Label(settings_frame, text="Sampler: -", style=STATUS_LABEL_STYLE)
        self.sampler_label.grid(row=0, column=1, sticky="w")
        self.steps_label = ttk.Label(settings_frame, text="Steps: -", style=STATUS_LABEL_STYLE)
        self.steps_label.grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        self.cfg_label = ttk.Label(settings_frame, text="CFG: -", style=STATUS_LABEL_STYLE)
        self.cfg_label.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.seed_label = ttk.Label(settings_frame, text="Seed: -", style=STATUS_LABEL_STYLE)
        self.seed_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.stage_summary_label = ttk.Label(self.body, text="Stages: -", style=STATUS_LABEL_STYLE)
        self.stage_summary_label.pack(anchor=tk.W, pady=(4, 0))

        self.stage_flags_label = ttk.Label(
            self.body,
            text=self._format_flags(refiner=False, hires=False, upscale=False),
            style=STATUS_LABEL_STYLE,
        )
        self.stage_flags_label.pack(anchor=tk.W, pady=(0, 4))

        self.randomizer_label = ttk.Label(self.body, text="Randomizer: OFF", style=STATUS_LABEL_STYLE)
        self.randomizer_label.pack(anchor=tk.W, pady=(0, 4))

        self.learning_metadata_label = ttk.Label(
            self.body,
            text="Learning metadata: N/A",
            style=STATUS_LABEL_STYLE,
        )
        self.learning_metadata_label.pack(anchor=tk.W)

        self.actions_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        self.actions_frame.pack(fill=tk.X, pady=(12, 0))
        self.actions_frame.columnconfigure((0, 1), weight=1)

        self.add_to_queue_button = ttk.Button(
            self.actions_frame,
            text="Add to Queue",
            style=PRIMARY_BUTTON_STYLE,
            command=self._on_add_to_queue,
        )
        self.add_to_queue_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.clear_draft_button = ttk.Button(
            self.actions_frame,
            text="Clear Draft",
            style=DANGER_BUTTON,
            command=self._on_clear_draft,
        )
        self.clear_draft_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._update_action_states(None)

    def set_jobs(self, jobs: list[Any]) -> None:
        """Update preview from a list of NormalizedJobRecord objects."""
        summaries: list[JobUiSummary] = []
        for job in jobs:
            if hasattr(job, "to_ui_summary"):
                summaries.append(job.to_ui_summary())
        self.set_job_summaries(summaries)

    def set_job_summaries(self, summaries: list[JobUiSummary]) -> None:
        """Render one or more JobUiSummary entries."""
        self._job_summaries = list(summaries)
        first_summary = summaries[0] if summaries else None
        self._render_summary(first_summary, len(summaries))

    def update_from_job_draft(self, job_draft: Any) -> None:
        """Update preview summary from job draft."""
        packs = getattr(job_draft, "packs", [])
        if not packs:
            self._render_summary(None, 0)
            self._update_action_states(job_draft)
            return

        entry = packs[0]
        summary = self._summary_from_pack_entry(entry)
        self._render_summary(summary, len(packs))
        self._update_action_states(job_draft)

    def update_from_controls(self, sidebar: Any) -> None:
        """Update preview summary from sidebar controls."""
        enabled: list[str] = getattr(sidebar, "get_enabled_stages", lambda: [])()
        ordered = ["txt2img", "img2img", "adetailer", "upscale"]
        canonical = [stage for stage in ordered if stage in set(enabled)]
        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        stages_text = " + ".join(stage_labels[stage] for stage in canonical) or "-"
        self.stage_summary_label.config(text=f"Stages: {stages_text}")

    def _summary_from_pack_entry(self, entry: Any) -> JobUiSummary:
        config = entry.config_snapshot or {}
        prompt_text = entry.prompt_text or str(config.get("prompt") or "")
        negative = entry.negative_prompt_text or str(config.get("negative_prompt", "") or "")
        sampler = str(config.get("sampler") or config.get("sampler_name") or "")
        steps = self._coerce_int(config.get("steps"))
        cfg_scale = self._coerce_float(config.get("cfg_scale"))

        model = str(config.get("model") or config.get("model_name") or entry.pack_name or "unknown") or "unknown"
        seed = config.get("seed")
        seed_display = str(seed) if seed is not None else "?"
        stage_flags = entry.stage_flags or {}
        stages = []
        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        for stage, label in stage_labels.items():
            if stage_flags.get(stage):
                stages.append(label)
        if not stages:
            stages.append("txt2img")
        stages_summary = " + ".join(stages)

        randomizer_summary = NormalizedJobRecord._format_randomizer_summary(entry.randomizer_metadata)

        has_refiner = bool(stage_flags.get("refiner") or config.get("refiner_enabled"))
        has_hires = bool(stage_flags.get("hires") or config.get("hires_enabled"))
        has_upscale = bool(stage_flags.get("upscale") or config.get("upscale_enabled"))
        output_dir = str(config.get("output_dir") or config.get("path_output_dir") or "output")

        return JobUiSummary(
            job_id=entry.pack_id,
            model=model,
            prompt_short=self._truncate_text(prompt_text, limit=120),
            negative_prompt_short=self._truncate_text(negative, limit=120) if negative else None,
            sampler=sampler,
            steps=steps,
            cfg_scale=cfg_scale,
            seed_display=seed_display,
            variant_label="",
            batch_label="",
            stages_summary=stages_summary,
            randomizer_summary=randomizer_summary,
            has_refiner=has_refiner,
            has_hires=has_hires,
            has_upscale=has_upscale,
            output_dir=output_dir,
            total_summary=f"{model} | seed={seed_display}",
        )

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        if not value:
            return ""
        return value if len(value) <= limit else value[:limit] + "..."

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update action button availability based on app_state."""
        if app_state is None:
            app_state = self.app_state
        job_draft = getattr(app_state, "job_draft", None)
        self._update_action_states(job_draft)

    def _render_summary(self, summary: JobUiSummary | None, total: int) -> None:
        if summary is None:
            self.job_count_label.config(text="No job selected")
            self._set_text_widget(self.prompt_text, "")
            self._set_text_widget(self.negative_prompt_text, "")
            self.model_label.config(text="Model: -")
            self.sampler_label.config(text="Sampler: -")
            self.steps_label.config(text="Steps: -")
            self.cfg_label.config(text="CFG: -")
            self.seed_label.config(text="Seed: -")
            self.stage_summary_label.config(text="Stages: -")
            self.stage_flags_label.config(
                text=self._format_flags(refiner=False, hires=False, upscale=False)
            )
            self.randomizer_label.config(text="Randomizer: OFF")
            self.learning_metadata_label.config(text="Learning metadata: N/A")
            return

        job_text = "Jobs: " + str(total) if total > 1 else "Job: 1"
        self.job_count_label.config(text=job_text)
        self._set_text_widget(self.prompt_text, summary.prompt_short)
        self._set_text_widget(self.negative_prompt_text, summary.negative_prompt_short or "")
        self.model_label.config(text=f"Model: {summary.model}")
        self.sampler_label.config(text=f"Sampler: {summary.sampler or '-'}")
        self.steps_label.config(
            text=f"Steps: {summary.steps if summary.steps is not None else '-'}"
        )
        cfg_value = summary.cfg_scale if summary.cfg_scale is not None else "-"
        self.cfg_label.config(text=f"CFG: {cfg_value}")
        self.seed_label.config(text=f"Seed: {summary.seed_display}")
        self.stage_summary_label.config(text=f"Stages: {summary.stages_summary}")

        flag_text = self._format_flags(
            refiner=summary.has_refiner,
            hires=summary.has_hires,
            upscale=summary.has_upscale,
        )
        self.stage_flags_label.config(text=flag_text)

        randomizer_text = summary.randomizer_summary or "OFF"
        self.randomizer_label.config(text=f"Randomizer: {randomizer_text}")
        self.learning_metadata_label.config(text="Learning metadata: N/A")

    @staticmethod
    def _format_flags(*, refiner: bool, hires: bool, upscale: bool) -> str:
        parts = [
            f"Refiner: {'ON' if refiner else 'OFF'}",
            f"HiRes: {'ON' if hires else 'OFF'}",
            f"Upscale: {'ON' if upscale else 'OFF'}",
        ]
        return " · ".join(parts)

    @staticmethod
    def _set_text_widget(widget: tk.Text, value: str) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.config(state=tk.DISABLED)

    def _on_add_to_queue(self) -> None:
        """Move the draft job into the queue."""
        self._invoke_controller("on_add_job_to_queue_v2")

    def _on_clear_draft(self) -> None:
        """Clear the current draft job metadata."""
        self._invoke_controller("on_clear_job_draft")

    def _on_details_clicked(self) -> None:
        """Show the logging view via controller helper."""
        self._invoke_controller("show_log_trace_panel")

    def _update_action_states(self, job_draft: Any | None) -> None:
        """Enable/disable action buttons based on draft content."""
        has_draft = False
        if job_draft is not None:
            packs = getattr(job_draft, "packs", [])
            has_draft = bool(packs)
        state = ["!disabled"] if has_draft else ["disabled"]
        self.add_to_queue_button.state(state)
        self.clear_draft_button.state(state)

    def _invoke_controller(self, method_name: str, *args: Any) -> Any:
        """Call a controller hook if available."""
        controller = self.controller
        if not controller:
            return None
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                return method(*args)
            except Exception:
                pass
        return None

Reviewing preview panel methods
I need to check out the methods in the preview panel, especially those interacting with the controller, like refresh or on_add_pack_to_job. These methods likely manage how the panel updates or responds to changes, so understanding them is crucial to ensure everything works as expected.

Identifying preview panel controller methods
with open(os.path.join(extract_dir,"src","gui","preview_panel_v2.py"),"r") as f:
    txt_prev = f.read()
for name in ["_refresh_from_pipeline","on_add_pack_to_job","refresh_preview_from_pipeline","add_to_queue","submit_preview_jobs_to_queue"]:
    if name in txt_prev:
        print("==",name,"==", txt_prev[txt_prev.index(name)-120:txt_prev.index(name)+260])

== add_to_queue == .actions_frame.pack(fill=tk.X, pady=(12, 0))
        self.actions_frame.columnconfigure((0, 1), weight=1)

        self.add_to_queue_button = ttk.Button(
            self.actions_frame,
            text="Add to Queue",
            style=PRIMARY_BUTTON_STYLE,
            command=self._on_add_to_queue,
        )
        self.add_to_queue_button.grid(row=0, column=0, sticky="ew", 
Extracting preview panel methods and interactions
print(txt_prev[txt_prev.index("def _on_add_to_queue"):txt_prev.index("def _invoke_controller")])

def _on_add_to_queue(self) -> None:
        """Move the draft job into the queue."""
        self._invoke_controller("on_add_job_to_queue_v2")

    def _on_clear_draft(self) -> None:
        """Clear the current draft job metadata."""
        self._invoke_controller("on_clear_job_draft")

    def _on_details_clicked(self) -> None:
        """Show the logging view via controller helper."""
        self._invoke_controller("show_log_trace_panel")

    def _update_action_states(self, job_draft: Any | None) -> None:
        """Enable/disable action buttons based on draft content."""
        has_draft = False
        if job_draft is not None:
            packs = getattr(job_draft, "packs", [])
            has_draft = bool(packs)
        state = ["!disabled"] if has_draft else ["disabled"]
        self.add_to_queue_button.state(state)
        self.clear_draft_button.state(state)

    
Checking controller methods for preview panel
The preview panel seems to depend on controller methods like on_add_job_to_queue_v2, on_clear_job_draft, and possibly other methods to refresh the preview from pipeline jobs. I’ll search for methods like on_add_pack_to_job in the app_controller to see how they interact.

Searching for controller methods in app_controller
with open(os.path.join(extract_dir,"src","controller","app_controller.py"),"r") as f:
    txt_app = f.read()
for name in ["on_add_packs_to_job","on_add_job_to_queue_v2","get_job_draft","get_job_history_service","get_preview_jobs","refresh_preview_from_pipeline"]:
    if name in txt_app:
        print("==",name,"==")

== on_add_job_to_queue_v2 ==
Searching for controller method occurrences in app_controller
print(txt_app[txt_app.index("on_add_job_to_queue_v2")-200:txt_app.index("on_add_job_to_queue_v2")+260])

_now_v2 handler {name} error: {exc!r}")
                    break

        self._ensure_run_mode_default("run_now")
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)

    def on_add_job_to_queue_v2(self) -> None:
        """Queue-first Add-to-Queue entrypoint; safe no-op if none available."""
        pipeline_ctrl = getattr(self, "pipeline_controller", None)
        if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_t
Searching controller methods in app_controller
print(txt_app[txt_app.index("def on_add_job_to_queue_v2"):txt_app.index("def on_clear_job_draft")])

--------------------

    def on_model_selected(self, model_name: str) -> None:
        self._append_log(f"[controller] Model selected: {model_name}")
        self.state.current_config.model_name = model_name
        self._apply_model_profile_defaults(model_name)

    def on_vae_selected(self, vae_name: str) -> None:
        self._append_log(f"[controller] VAE selected: {vae_name}")
        self.state.current_config.vae_name = vae_name

    def on_sampler_selected(self, sampler_name: str) -> None:
        self._append_log(f"[controller] Sampler selected: {sampler_name}")
        self.state.current_config.sampler_name = sampler_name

    def on_scheduler_selected(self, scheduler_name: str) -> None:
        self._append_log(f"[controller] Scheduler selected: {scheduler_name}")
        self.state.current_config.scheduler_name = scheduler_name

    def on_resolution_changed(self, width: int, height: int) -> None:
        self._append_log(f"[controller] Resolution changed to {width}x{height}")
        self.state.current_config.width = width
        self.state.current_config.height = height

    def on_randomization_toggled(self, enabled: bool) -> None:
        self._append_log(f"[controller] Randomization toggled: {enabled}")
        self.state.current_config.randomization_enabled = enabled
        self._update_run_config_randomizer(enabled=enabled)

    def on_randomizer_max_variants_changed(self, value: int) -> None:
        try:
            normalized = max(1, int(value))
        except (TypeError, ValueError):
            normalized = 1
        self._append_log(f"[controller] Randomizer max variants set to {normalized}")
        self.state.current_config.max_variants = normalized
        self._update_run_config_randomizer(max_variants=normalized)

    def on_matrix_base_prompt_changed(self, text: str) -> None:
        self._append_log("[controller] Matrix base prompt changed (stub).")
        # TODO: store in matrix config.

    def on_matrix_slots_changed(self) -> None:
        self._append_log("[controller] Matrix slots changed (stub).")
        # TODO: store in matrix config.

    # ------------------------------------------------------------------
    # Preview / Right Zone
    # ------------------------------------------------------------------

    def on_request_preview_refresh(self) -> None:
        self._append_log("[controller] Preview refresh requested (stub).")
        # TODO: set preview_label image or text based on latest run or preview.

    def _empty_resource_map(self) -> dict[str, list[Any]]:
        return {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
            "adetailer_models": [],
            "adetailer_detectors": [],
        }

    def refresh_resources_from_webui(self) -> dict[str, list[Any]] | None:
        if not getattr(self, "resource_service", None):
            return None
        try:
            payload = self.resource_service.refresh_all() or {}
        except Exception as exc:
            message = f"Failed to refresh WebUI resources: {exc}"
            self._append_log(f"[resources] {message}")
            logger.warning(message)
            return None

        normalized = self._normalize_resource_map(payload)
        self.state.resources = normalized
        if self.app_state is not None:
            try:
                self.app_state.set_resources(normalized)
            except Exception:
                pass
        self._update_gui_dropdowns()
        counts = tuple(len(normalized[key]) for key in ("models", "vaes", "samplers", "schedulers", "upscalers"))
        msg = (
            f"Resource update: {counts[0]} models, {counts[1]} vaes, "
            f"{counts[2]} samplers, {counts[3]} schedulers, {counts[4]} upscalers"
        )
        self._append_log(f"[resources] {msg}")
        logger.info(msg)
        return normalized

    def on_webui_ready(self) -> None:
        """Handle WebUI transitioning to READY."""
        self._append_log("[webui] READY received, refreshing resource lists.")
        self.refresh_resources_from_webui()

    def _normalize_resource_map(self, payload: dict[str, Any]) -> dict[str, list[Any]]:
        resources = self._empty_resource_map()
        for name in resources:
            resources[name] = list(payload.get(name) or [])
        resources["adetailer_models"] = list(payload.get("adetailer_models") or [])
        resources["adetailer_detectors"] = list(payload.get("adetailer_detectors") or [])
        return resources

    def _update_gui_dropdowns(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        dropdowns = self._dropdown_loader.load_dropdowns(self, self.app_state)
        self._dropdown_loader.apply_to_gui(pipeline_tab, dropdowns)
        
        # Also refresh the sidebar's core config panel
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "refresh_core_config_from_webui"):
            try:
                sidebar.refresh_core_config_from_webui()
            except Exception as e:
                pass

    def _get_stage_cards_panel(self) -> Any:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return None
        return getattr(pipeline_tab, "stage_cards_panel", None)

    def _get_sidebar_panel(self) -> Any:
        return getattr(self.main_window, "sidebar_panel_v2", None)

    # ------------------------------------------------------------------
    # Pipeline Pack Config & Job Builder (PR-035)
    # ------------------------------------------------------------------

    def _maybe_set_app_state_lora_strengths(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        strengths = normalize_lora_strengths(config.get("lora_strengths"))
        self.app_state.set_lora_strengths(strengths)

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        if stage != "adetailer" or not self.app_state:
            return
        normalized = bool(enabled)
        self.app_state.set_adetailer_enabled(normalized)
        config_snapshot = self._collect_adetailer_panel_config()
        config_snapshot["enabled"] = normalized
        self.app_state.set_adetailer_config(config_snapshot)

    def on_adetailer_config_changed(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        snapshot = dict(config or {})
        snapshot["enabled"] = bool(self.app_state.adetailer_enabled)
        self.app_state.set_adetailer_config(snapshot)

    def _collect_adetailer_panel_config(self) -> dict[str, Any]:
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "collect_adetailer_config"):
            try:
                return dict(panel.collect_adetailer_config() or {})
            except Exception:
                pass
        if self.app_state:
            return dict(self.app_state.adetailer_config or {})
        return {}

    def _apply_adetailer_config_section(self, config: dict[str, Any]) -> None:
        if not config:
            pipeline_section = {}
            ad_config = {}
        else:
            pipeline_section = config.get("pipeline") or {}
            ad_config = config.get("adetailer") or {}
        enabled = bool(pipeline_section.get("adetailer_enabled") or ad_config.get("enabled"))
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "load_adetailer_config"):
            panel.load_adetailer_config(ad_config)
        if panel and hasattr(panel, "set_stage_enabled"):
            panel.set_stage_enabled("adetailer", enabled)
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "set_stage_state"):
            sidebar.set_stage_state("adetailer", enabled)
        if self.app_state:
            snapshot = dict(ad_config)
            snapshot["enabled"] = enabled
            self.app_state.set_adetailer_enabled(enabled)
            self.app_state.set_adetailer_config(snapshot)

    def _update_run_config_randomizer(self, enabled: bool | None = None, max_variants: int | None = None) -> None:
        if not self.app_state:
            return
        current = dict(self.app_state.run_config or {})
        updated = False
        if enabled is not None and current.get("randomization_enabled") != enabled:
            current["randomization_enabled"] = enabled
            updated = True
        if max_variants is not None and current.get("max_variants") != max_variants:
            current["max_variants"] = max_variants
            updated = True
        if updated:
            self.app_state.set_run_config(current)

    def _apply_randomizer_from_config(self, config: dict[str, Any]) -> None:
        if not config:
            return
        fallback = self.state.current_config
        random_section = config.get("randomization") or {}
        enabled = config.get("randomization_enabled")
        if enabled is None:
            enabled = random_section.get("enabled", fallback.randomization_enabled)
        max_variants = config.get("max_variants")
        if max_variants is None:
            max_variants = random_section.get("max_variants", fallback.max_variants)
        try:
            normalized_max = int(max_variants)
        except (TypeError, ValueError):
            normalized_max = fallback.max_variants
        normalized_max = max(1, normalized_max)
        normalized_enabled = bool(enabled)
        fallback.randomization_enabled = normalized_enabled
        fallback.max_variants = normalized_max
        self._update_run_config_randomizer(enabled=normalized_enabled, max_variants=normalized_max)

    def _get_panel_randomizer_config(self) -> dict[str, Any] | None:
        panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if panel is None or not hasattr(panel, "get_randomizer_config"):
            return None
        try:
            config = panel.get_randomizer_config()
        except Exception:
            return None
        if not config:
            return None
        return config

    def _run_config_with_lora(self) -> dict[str, Any]:
        base = self.app_state.run_config.copy() if self.app_state else {}
        if self.app_state and self.app_state.lora_strengths:
            base["lora_strengths"] = [cfg.to_dict() for cfg in self.app_state.lora_strengths]
        if "randomization_enabled" not in base:
            base["randomization_enabled"] = self.state.current_config.randomization_enabled
        if "max_variants" not in base:
            base["max_variants"] = self.state.current_config.max_variants
        return base

    def _lora_settings_payload(self) -> dict[str, dict[str, Any]] | None:
        if not self.app_state:
            return None
        payload = {}
        for config in self.app_state.lora_strengths:
            if config.name:
                payload[config.name] = config.to_dict()
        return payload or None

    def _build_job_from_draft(self) -> Job | None:
        if not self.app_state:
            self._append_log("[controller] Cannot build job - AppState missing.")
            return None
        if not self.app_state.job_draft.packs:
            self._append_log("[controller] Job draft is empty, skipping queue action.")
            return None
        job = Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=None,
            payload=self._job_payload_from_draft(),
            lora_settings=self._lora_settings_payload(),
        )
        return job

    def _job_payload_from_draft(self) -> dict[str, Any]:
        if not self.app_state:
            return {}
        packs = [
            {
                "pack_id": entry.pack_id,
                "pack_name": entry.pack_name,
                "config_snapshot": entry.config_snapshot,
            }
            for entry in self.app_state.job_draft.packs
        ]
        payload = {"packs": packs, "run_config": self._run_config_with_lora()}
        return payload

    def get_lora_runtime_settings(self) -> list[dict[str, Any]]:
        if not self.app_state:
            return []
        return [cfg.to_dict() for cfg in self.app_state.lora_strengths]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = float(strength)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, strength=normalized, enabled=True))
        self.app_state.set_lora_strengths(updated)

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, enabled=normalized))
        self.app_state.set_lora_strengths(updated)


    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
        """Load a pack's config into the stage cards."""
        self._append_log(f"[controller] Loading config for pack: {pack_id}")
        
        # Try to load pack config via ConfigManager
        pack_config = self._config_manager.load_pack_config(pack_id)
        if pack_config is None:
            self._append_log(f"[controller] No config found for pack: {pack_id}")
            return
        pipeline_section = pack_config.get("pipeline") or {}
        self._apply_pipeline_stage_flags(pipeline_section)
        
        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(pack_config)
            self._maybe_set_app_state_lora_strengths(pack_config)
            self._apply_randomizer_from_config(pack_config)
        
        # Update stage cards if available
        pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
            try:
                pipeline_config_panel.apply_run_config(pack_config)
            except Exception as e:
                self._append_log(f"[controller] Error applying pack config to stages: {e}")
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, pack_config)
            stage_panel.load_adetailer_config(pack_config.get("adetailer") or {})
        self._apply_adetailer_config_section(pack_config)
        
        self._append_log(f"[controller] Loaded config for pack '{pack_id}'")

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        """Write current stage config into one or more packs."""
        self._append_log(f"[controller] Applying config to packs: {pack_ids}")
        
        # Get current run config
        current_config = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            current_config.update(panel_randomizer)
        if not current_config:
            self._append_log("[controller] No current config to apply")
            return
        if self.app_state:
            self.app_state.set_run_config(current_config)
        
        # Save to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, current_config)
            if success:
                self._append_log(f"[controller] Applied config to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply config to pack '{pack_id}'")

    def save_current_pipeline_preset(self, preset_name: str) -> bool:
        """Persist the current pipeline/stage config as a named preset."""
        self._append_log(f"[controller] Saving current pipeline config as preset '{preset_name}'")
        payload = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            payload.update(panel_randomizer)
        if not payload:
            self._append_log("[controller] No current config to save as preset")
            return False
        success = self._config_manager.save_preset(preset_name, payload)
        if success:
            self._append_log(f"[controller] Preset '{preset_name}' saved")
        else:
            self._append_log(f"[controller] Failed to save preset '{preset_name}'")
        return success

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        """Add one or more packs to the current job draft."""
        self._append_log(f"[controller] Adding packs to job: {pack_ids}")
        
        entries = []
        stage_flags = self._build_stage_flags()
        randomizer_metadata = self._build_randomizer_metadata()
        for pack_id in pack_ids:
            pack = self._find_pack_by_id(pack_id)
            if pack is None:
                self._append_log(f"[controller] Pack not found: {pack_id}")
                continue
            
            # Get current run config from app_state
            run_config = self._run_config_with_lora()
            
            # Ensure randomization is included
            if "randomization_enabled" not in run_config:
                run_config["randomization_enabled"] = self.state.current_config.randomization_enabled
            prompt_text, negative_prompt_text = self._read_pack_prompts(pack)
            entry = PackJobEntry(
                pack_id=pack_id,
                pack_name=pack.name,
                config_snapshot=run_config,
                prompt_text=prompt_text,
                negative_prompt_text=negative_prompt_text,
                stage_flags=dict(stage_flags),
                randomizer_metadata=randomizer_metadata,
            )
            entries.append(entry)
        
        if entries and self.app_state:
            self.app_state.add_packs_to_job_draft(entries)
            self._append_log(f"[controller] Added {len(entries)} pack(s) to job draft")

    def on_add_job_to_queue(self) -> None:
        """Enqueue the current job draft."""
        job = self._build_job_from_draft()
        if job is None:
            return
        if not self.job_service:
            return
        self.job_service.enqueue(job)
        payload = job.payload if isinstance(job.payload, dict) else {}
        packs = payload.get("packs", [])
        pack_count = len(packs) if isinstance(packs, list) else 0
        self._append_log(f"[controller] Enqueued job {job.job_id} with {pack_count} pack(s)")

    def on_run_job_now(self) -> None:
        """Enqueue and execute the next queued job via JobService."""
        self.on_run_queue_now_clicked()

    def on_run_queue_now_clicked(self) -> None:
        """Delegate to JobService to execute the next queued job."""
        job = self._build_job_from_draft()
        if job is None or not self.job_service:
            return
        self.job_service.run_now(job)
        self._append_log(f"[controller] Running job {job.job_id} immediately")

    
Investigating job models and pipeline path
It looks like the on_run_queue_now_clicked method builds a job from a draft using job_service.run_now, but I didn’t find an updated pipeline v2 path. It seems like the older job draft model is still in use. The on_add_job_to_queue_v2 method is also truncated, so I’ll need to view more lines below for clarity.

Extracting code snippet for job queue function
snippet = txt_app[txt_app.index("def on_add_job_to_queue_v2"):txt_app.index("def on_run_job_now")]
print(snippet)


Investigating possible incorrect indices
It seems like the indices might be off. I think I’ll look up the function's definition and gather more context from it. That should help me understand if there's an issue with how the indices are being used or if something else is going on.

Searching for function definition in text
loc = txt_app.index("on_add_job_to_queue_v2")
print(txt_app[loc-400:loc+400])

ntroller] on_run_job_now_v2 using {name}.")
                    return handler()
                except Exception as exc:  # noqa: BLE001
                    self._append_log(f"[controller] on_run_job_now_v2 handler {name} error: {exc!r}")
                    break

        self._ensure_run_mode_default("run_now")
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)

    def on_add_job_to_queue_v2(self) -> None:
        """Queue-first Add-to-Queue entrypoint; safe no-op if none available."""
        pipeline_ctrl = getattr(self, "pipeline_controller", None)
        if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_to_queue"):
            try:
                count = pipeline_ctrl.submit_preview_jobs_to_queue(
                    source="gui",
          
Searching for function definition with context
print(txt_app[loc+400:loc+800])

          prompt_source="pack",
                )
                if count > 0:
                    self._append_log(f"[controller] Submitted {count} job(s) from preview to queue")
                    return
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[controller] submit_preview_jobs_to_queue error: {exc!r}")

        handler_names = ("on_add_job_to_queu
Revisiting truncated data index
It seems once again the data is being cut off due to index issues. I’ll need to acquire the full data instead of a truncated version to complete my assessment. Let's try accessing the data correctly to gather everything needed.

Extracting code between specific function definitions
start = txt_app.index("    def on_add_job_to_queue_v2")
end = txt_app.index("    def on_clear_job_draft")
print(txt_app[start:end])

------------------------

    def on_model_selected(self, model_name: str) -> None:
        self._append_log(f"[controller] Model selected: {model_name}")
        self.state.current_config.model_name = model_name
        self._apply_model_profile_defaults(model_name)

    def on_vae_selected(self, vae_name: str) -> None:
        self._append_log(f"[controller] VAE selected: {vae_name}")
        self.state.current_config.vae_name = vae_name

    def on_sampler_selected(self, sampler_name: str) -> None:
        self._append_log(f"[controller] Sampler selected: {sampler_name}")
        self.state.current_config.sampler_name = sampler_name

    def on_scheduler_selected(self, scheduler_name: str) -> None:
        self._append_log(f"[controller] Scheduler selected: {scheduler_name}")
        self.state.current_config.scheduler_name = scheduler_name

    def on_resolution_changed(self, width: int, height: int) -> None:
        self._append_log(f"[controller] Resolution changed to {width}x{height}")
        self.state.current_config.width = width
        self.state.current_config.height = height

    def on_randomization_toggled(self, enabled: bool) -> None:
        self._append_log(f"[controller] Randomization toggled: {enabled}")
        self.state.current_config.randomization_enabled = enabled
        self._update_run_config_randomizer(enabled=enabled)

    def on_randomizer_max_variants_changed(self, value: int) -> None:
        try:
            normalized = max(1, int(value))
        except (TypeError, ValueError):
            normalized = 1
        self._append_log(f"[controller] Randomizer max variants set to {normalized}")
        self.state.current_config.max_variants = normalized
        self._update_run_config_randomizer(max_variants=normalized)

    def on_matrix_base_prompt_changed(self, text: str) -> None:
        self._append_log("[controller] Matrix base prompt changed (stub).")
        # TODO: store in matrix config.

    def on_matrix_slots_changed(self) -> None:
        self._append_log("[controller] Matrix slots changed (stub).")
        # TODO: store in matrix config.

    # ------------------------------------------------------------------
    # Preview / Right Zone
    # ------------------------------------------------------------------

    def on_request_preview_refresh(self) -> None:
        self._append_log("[controller] Preview refresh requested (stub).")
        # TODO: set preview_label image or text based on latest run or preview.

    def _empty_resource_map(self) -> dict[str, list[Any]]:
        return {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
            "adetailer_models": [],
            "adetailer_detectors": [],
        }

    def refresh_resources_from_webui(self) -> dict[str, list[Any]] | None:
        if not getattr(self, "resource_service", None):
            return None
        try:
            payload = self.resource_service.refresh_all() or {}
        except Exception as exc:
            message = f"Failed to refresh WebUI resources: {exc}"
            self._append_log(f"[resources] {message}")
            logger.warning(message)
            return None

        normalized = self._normalize_resource_map(payload)
        self.state.resources = normalized
        if self.app_state is not None:
            try:
                self.app_state.set_resources(normalized)
            except Exception:
                pass
        self._update_gui_dropdowns()
        counts = tuple(len(normalized[key]) for key in ("models", "vaes", "samplers", "schedulers", "upscalers"))
        msg = (
            f"Resource update: {counts[0]} models, {counts[1]} vaes, "
            f"{counts[2]} samplers, {counts[3]} schedulers, {counts[4]} upscalers"
        )
        self._append_log(f"[resources] {msg}")
        logger.info(msg)
        return normalized

    def on_webui_ready(self) -> None:
        """Handle WebUI transitioning to READY."""
        self._append_log("[webui] READY received, refreshing resource lists.")
        self.refresh_resources_from_webui()

    def _normalize_resource_map(self, payload: dict[str, Any]) -> dict[str, list[Any]]:
        resources = self._empty_resource_map()
        for name in resources:
            resources[name] = list(payload.get(name) or [])
        resources["adetailer_models"] = list(payload.get("adetailer_models") or [])
        resources["adetailer_detectors"] = list(payload.get("adetailer_detectors") or [])
        return resources

    def _update_gui_dropdowns(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        dropdowns = self._dropdown_loader.load_dropdowns(self, self.app_state)
        self._dropdown_loader.apply_to_gui(pipeline_tab, dropdowns)
        
        # Also refresh the sidebar's core config panel
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "refresh_core_config_from_webui"):
            try:
                sidebar.refresh_core_config_from_webui()
            except Exception as e:
                pass

    def _get_stage_cards_panel(self) -> Any:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return None
        return getattr(pipeline_tab, "stage_cards_panel", None)

    def _get_sidebar_panel(self) -> Any:
        return getattr(self.main_window, "sidebar_panel_v2", None)

    # ------------------------------------------------------------------
    # Pipeline Pack Config & Job Builder (PR-035)
    # ------------------------------------------------------------------

    def _maybe_set_app_state_lora_strengths(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        strengths = normalize_lora_strengths(config.get("lora_strengths"))
        self.app_state.set_lora_strengths(strengths)

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        if stage != "adetailer" or not self.app_state:
            return
        normalized = bool(enabled)
        self.app_state.set_adetailer_enabled(normalized)
        config_snapshot = self._collect_adetailer_panel_config()
        config_snapshot["enabled"] = normalized
        self.app_state.set_adetailer_config(config_snapshot)

    def on_adetailer_config_changed(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        snapshot = dict(config or {})
        snapshot["enabled"] = bool(self.app_state.adetailer_enabled)
        self.app_state.set_adetailer_config(snapshot)

    def _collect_adetailer_panel_config(self) -> dict[str, Any]:
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "collect_adetailer_config"):
            try:
                return dict(panel.collect_adetailer_config() or {})
            except Exception:
                pass
        if self.app_state:
            return dict(self.app_state.adetailer_config or {})
        return {}

    def _apply_adetailer_config_section(self, config: dict[str, Any]) -> None:
        if not config:
            pipeline_section = {}
            ad_config = {}
        else:
            pipeline_section = config.get("pipeline") or {}
            ad_config = config.get("adetailer") or {}
        enabled = bool(pipeline_section.get("adetailer_enabled") or ad_config.get("enabled"))
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "load_adetailer_config"):
            panel.load_adetailer_config(ad_config)
        if panel and hasattr(panel, "set_stage_enabled"):
            panel.set_stage_enabled("adetailer", enabled)
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "set_stage_state"):
            sidebar.set_stage_state("adetailer", enabled)
        if self.app_state:
            snapshot = dict(ad_config)
            snapshot["enabled"] = enabled
            self.app_state.set_adetailer_enabled(enabled)
            self.app_state.set_adetailer_config(snapshot)

    def _update_run_config_randomizer(self, enabled: bool | None = None, max_variants: int | None = None) -> None:
        if not self.app_state:
            return
        current = dict(self.app_state.run_config or {})
        updated = False
        if enabled is not None and current.get("randomization_enabled") != enabled:
            current["randomization_enabled"] = enabled
            updated = True
        if max_variants is not None and current.get("max_variants") != max_variants:
            current["max_variants"] = max_variants
            updated = True
        if updated:
            self.app_state.set_run_config(current)

    def _apply_randomizer_from_config(self, config: dict[str, Any]) -> None:
        if not config:
            return
        fallback = self.state.current_config
        random_section = config.get("randomization") or {}
        enabled = config.get("randomization_enabled")
        if enabled is None:
            enabled = random_section.get("enabled", fallback.randomization_enabled)
        max_variants = config.get("max_variants")
        if max_variants is None:
            max_variants = random_section.get("max_variants", fallback.max_variants)
        try:
            normalized_max = int(max_variants)
        except (TypeError, ValueError):
            normalized_max = fallback.max_variants
        normalized_max = max(1, normalized_max)
        normalized_enabled = bool(enabled)
        fallback.randomization_enabled = normalized_enabled
        fallback.max_variants = normalized_max
        self._update_run_config_randomizer(enabled=normalized_enabled, max_variants=normalized_max)

    def _get_panel_randomizer_config(self) -> dict[str, Any] | None:
        panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if panel is None or not hasattr(panel, "get_randomizer_config"):
            return None
        try:
            config = panel.get_randomizer_config()
        except Exception:
            return None
        if not config:
            return None
        return config

    def _run_config_with_lora(self) -> dict[str, Any]:
        base = self.app_state.run_config.copy() if self.app_state else {}
        if self.app_state and self.app_state.lora_strengths:
            base["lora_strengths"] = [cfg.to_dict() for cfg in self.app_state.lora_strengths]
        if "randomization_enabled" not in base:
            base["randomization_enabled"] = self.state.current_config.randomization_enabled
        if "max_variants" not in base:
            base["max_variants"] = self.state.current_config.max_variants
        return base

    def _lora_settings_payload(self) -> dict[str, dict[str, Any]] | None:
        if not self.app_state:
            return None
        payload = {}
        for config in self.app_state.lora_strengths:
            if config.name:
                payload[config.name] = config.to_dict()
        return payload or None

    def _build_job_from_draft(self) -> Job | None:
        if not self.app_state:
            self._append_log("[controller] Cannot build job - AppState missing.")
            return None
        if not self.app_state.job_draft.packs:
            self._append_log("[controller] Job draft is empty, skipping queue action.")
            return None
        job = Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=None,
            payload=self._job_payload_from_draft(),
            lora_settings=self._lora_settings_payload(),
        )
        return job

    def _job_payload_from_draft(self) -> dict[str, Any]:
        if not self.app_state:
            return {}
        packs = [
            {
                "pack_id": entry.pack_id,
                "pack_name": entry.pack_name,
                "config_snapshot": entry.config_snapshot,
            }
            for entry in self.app_state.job_draft.packs
        ]
        payload = {"packs": packs, "run_config": self._run_config_with_lora()}
        return payload

    def get_lora_runtime_settings(self) -> list[dict[str, Any]]:
        if not self.app_state:
            return []
        return [cfg.to_dict() for cfg in self.app_state.lora_strengths]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = float(strength)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, strength=normalized, enabled=True))
        self.app_state.set_lora_strengths(updated)

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, enabled=normalized))
        self.app_state.set_lora_strengths(updated)


    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
        """Load a pack's config into the stage cards."""
        self._append_log(f"[controller] Loading config for pack: {pack_id}")
        
        # Try to load pack config via ConfigManager
        pack_config = self._config_manager.load_pack_config(pack_id)
        if pack_config is None:
            self._append_log(f"[controller] No config found for pack: {pack_id}")
            return
        pipeline_section = pack_config.get("pipeline") or {}
        self._apply_pipeline_stage_flags(pipeline_section)
        
        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(pack_config)
            self._maybe_set_app_state_lora_strengths(pack_config)
            self._apply_randomizer_from_config(pack_config)
        
        # Update stage cards if available
        pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
            try:
                pipeline_config_panel.apply_run_config(pack_config)
            except Exception as e:
                self._append_log(f"[controller] Error applying pack config to stages: {e}")
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, pack_config)
            stage_panel.load_adetailer_config(pack_config.get("adetailer") or {})
        self._apply_adetailer_config_section(pack_config)
        
        self._append_log(f"[controller] Loaded config for pack '{pack_id}'")

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        """Write current stage config into one or more packs."""
        self._append_log(f"[controller] Applying config to packs: {pack_ids}")
        
        # Get current run config
        current_config = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            current_config.update(panel_randomizer)
        if not current_config:
            self._append_log("[controller] No current config to apply")
            return
        if self.app_state:
            self.app_state.set_run_config(current_config)
        
        # Save to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, current_config)
            if success:
                self._append_log(f"[controller] Applied config to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply config to pack '{pack_id}'")

    def save_current_pipeline_preset(self, preset_name: str) -> bool:
        """Persist the current pipeline/stage config as a named preset."""
        self._append_log(f"[controller] Saving current pipeline config as preset '{preset_name}'")
        payload = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            payload.update(panel_randomizer)
        if not payload:
            self._append_log("[controller] No current config to save as preset")
            return False
        success = self._config_manager.save_preset(preset_name, payload)
        if success:
            self._append_log(f"[controller] Preset '{preset_name}' saved")
        else:
            self._append_log(f"[controller] Failed to save preset '{preset_name}'")
        return success

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        """Add one or more packs to the current job draft."""
        self._append_log(f"[controller] Adding packs to job: {pack_ids}")
        
        entries = []
        stage_flags = self._build_stage_flags()
        randomizer_metadata = self._build_randomizer_metadata()
        for pack_id in pack_ids:
            pack = self._find_pack_by_id(pack_id)
            if pack is None:
                self._append_log(f"[controller] Pack not found: {pack_id}")
                continue
            
            # Get current run config from app_state
            run_config = self._run_config_with_lora()
            
            # Ensure randomization is included
            if "randomization_enabled" not in run_config:
                run_config["randomization_enabled"] = self.state.current_config.randomization_enabled
            prompt_text, negative_prompt_text = self._read_pack_prompts(pack)
            entry = PackJobEntry(
                pack_id=pack_id,
                pack_name=pack.name,
                config_snapshot=run_config,
                prompt_text=prompt_text,
                negative_prompt_text=negative_prompt_text,
                stage_flags=dict(stage_flags),
                randomizer_metadata=randomizer_metadata,
            )
            entries.append(entry)
        
        if entries and self.app_state:
            self.app_state.add_packs_to_job_draft(entries)
            self._append_log(f"[controller] Added {len(entries)} pack(s) to job draft")

    def on_add_job_to_queue(self) -> None:
        """Enqueue the current job draft."""
        job = self._build_job_from_draft()
        if job is None:
            return
        if not self.job_service:
            return
        self.job_service.enqueue(job)
        payload = job.payload if isinstance(job.payload, dict) else {}
        packs = payload.get("packs", [])
        pack_count = len(packs) if isinstance(packs, list) else 0
        self._append_log(f"[controller] Enqueued job {job.job_id} with {pack_count} pack(s)")

    def on_run_job_now(self) -> None:
        """Enqueue and execute the next queued job via JobService."""
        self.on_run_queue_now_clicked()

    def on_run_queue_now_clicked(self) -> None:
        """Delegate to JobService to execute the next queued job."""
        job = self._build_job_from_draft()
        if job is None or not self.job_service:
            return
        self.job_service.run_now(job)
        self._append_log(f"[controller] Running job {job.job_id} immediately")


Investigating printed segment issue
It looks like I printed the wrong segment — I suspect this might be due to multiple definitions in the file or mis-indexing the substring boundaries. It could be easier to check by printing around the line numbers near the 'on_add_job_to_queue_v2' function. Let's show 200 lines for context.

Printing surrounding lines of code for function match
lines = txt_app.splitlines()
for i,l in enumerate(lines):
    if "on_add_job_to_queue_v2" in l:
        for j in range(i-10, i+40):
            if 0 <= j < len(lines):
                print(f"{j+1:4}: {lines[j]}")
        break
 457:                 try:
 458:                     self._append_log(f"[controller] on_run_job_now_v2 using {name}.")
 459:                     return handler()
 460:                 except Exception as exc:  # noqa: BLE001
 461:                     self._append_log(f"[controller] on_run_job_now_v2 handler {name} error: {exc!r}")
 462:                     break
 463: 
 464:         self._ensure_run_mode_default("run_now")
 465:         return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)
 466: 
 467:     def on_add_job_to_queue_v2(self) -> None:
 468:         """Queue-first Add-to-Queue entrypoint; safe no-op if none available."""
 469:         pipeline_ctrl = getattr(self, "pipeline_controller", None)
 470:         if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_to_queue"):
 471:             try:
 472:                 count = pipeline_ctrl.submit_preview_jobs_to_queue(
 473:                     source="gui",
 474:                     prompt_source="pack",
 475:                 )
 476:                 if count > 0:
 477:                     self._append_log(f"[controller] Submitted {count} job(s) from preview to queue")
 478:                     return
 479:             except Exception as exc:  # noqa: BLE001
 480:                 self._append_log(f"[controller] submit_preview_jobs_to_queue error: {exc!r}")
 481: 
 482:         handler_names = ("on_add_job_to_queue", "on_add_to_queue")
 483:         for name in handler_names:
 484:             handler = getattr(self, name, None)
 485:             if callable(handler):
 486:                 try:
 487:                     self._append_log(f"[controller] on_add_job_to_queue_v2 using {name}.")
 488:                     handler()
 489:                     return
 490:                 except Exception as exc:  # noqa: BLE001
 491:                     self._append_log(
 492:                         f"[controller] on_add_job_to_queue_v2 handler {name} error: {exc!r}"
 493:                     )
 494:                     return
 495: 
 496:         self._ensure_run_mode_default("add_to_queue")
 497:         self._start_run_v2(RunMode.QUEUE, RunSource.ADD_TO_QUEUE_BUTTON)
 498: 
 499:     def set_main_window(self, main_window: MainWindow) -> None:
 500:         """Set the main window and wire GUI callbacks."""
 501:         self.main_window = main_window
 502:         self.app_state = getattr(main_window, "app_state", None)
 503:         self._attach_to_gui()
 504:         if hasattr(self.main_window, "connect_controller"):
 505:             self.main_window.connect_controller(self)
 506: 
Displaying specific code lines
Alright, to get more clarity, let's view lines 470 through 492. This should give me a better perspective on what might be causing the issue and help pinpoint the problem more effectively. Let's dive into those specific lines and see what's going on!

Extracting specific lines from text file
for j in range(467, 495):
    print(f"{j+1:4}: {lines[j]}")

 468:         """Queue-first Add-to-Queue entrypoint; safe no-op if none available."""
 469:         pipeline_ctrl = getattr(self, "pipeline_controller", None)
 470:         if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_to_queue"):
 471:             try:
 472:                 count = pipeline_ctrl.submit_preview_jobs_to_queue(
 473:                     source="gui",
 474:                     prompt_source="pack",
 475:                 )
 476:                 if count > 0:
 477:                     self._append_log(f"[controller] Submitted {count} job(s) from preview to queue")
 478:                     return
 479:             except Exception as exc:  # noqa: BLE001
 480:                 self._append_log(f"[controller] submit_preview_jobs_to_queue error: {exc!r}")
 481: 
 482:         handler_names = ("on_add_job_to_queue", "on_add_to_queue")
 483:         for name in handler_names:
 484:             handler = getattr(self, name, None)
 485:             if callable(handler):
 486:                 try:
 487:                     self._append_log(f"[controller] on_add_job_to_queue_v2 using {name}.")
 488:                     handler()
 489:                     return
 490:                 except Exception as exc:  # noqa: BLE001
 491:                     self._append_log(
 492:                         f"[controller] on_add_job_to_queue_v2 handler {name} error: {exc!r}"
 493:                     )
 494:                     return
 495: 
Investigating the draft mechanisms for "Add to Job"
I think the path is clear: the preview panel's "Add to Queue" triggers app_controller.on_add_job_to_queue_v2, which calls PipelineController.submit_preview_jobs_to_queue when available, or else it falls back to the legacy batch. Earlier, CODEX pointed out that "Add to Job" only affects the draft pack list, so now I need to dig into the draft mechanisms like app_state_v2 and pipeline_controller.get_preview_jobs to figure out what’s going wrong.

Inspecting job draft mechanisms and preview handling
with open(os.path.join(extract_dir,"src","gui","app_state_v2.py"),"r") as f:
    txt_state = f.read()
print(txt_state[:260])

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.gui.gui_invoker import GuiInvoker
from src.queue.job_history_store import JobHistoryEntr
Inspecting job draft mechanisms in code
for i,l in enumerate(txt_state.splitlines()):
    if "class JobDraft" in l or "job_draft" in l:
        print(i+1, l)

31 class JobDraft:
97     job_draft: JobDraft = field(default_factory=JobDraft)
303     def add_packs_to_job_draft(self, entries: list[PackJobEntry]) -> None:
304         self.job_draft.packs.extend(entries)
305         self._notify("job_draft")
307     def clear_job_draft(self) -> None:
308         self.job_draft.packs.clear()
309         self._notify("job_draft")
Inspecting draft mechanisms for job queueing
print("\n".join(txt_state.splitlines()[31:120]))

    packs: list[PackJobEntry] = field(default_factory=list)


@dataclass
class CurrentConfig:
    """Lightweight facade for the currently selected run configuration."""

    preset_name: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    batch_size: int = 1
    seed: int | None = None
    randomization_enabled: bool = False
    max_variants: int = 1
    refiner_enabled: bool = False
    refiner_model_name: str = ""
    refiner_switch_at: float = 0.8
    hires_enabled: bool = False
    hires_upscaler_name: str = "Latent"
    hires_upscale_factor: float = 2.0
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True


@dataclass
class AppStateV2:
    """Central GUI-facing state container for the V2 application."""

    _listeners: Dict[str, List[Listener]] = field(default_factory=dict)
    _invoker: Optional[GuiInvoker] = None
    _notifications_enabled: bool = True

    prompt: str = ""
    negative_prompt: str = ""
    current_pack: Optional[str] = None
    is_running: bool = False
    controller: Optional[Any] = None
    status_text: str = "Idle"
    last_error: Optional[str] = None
    webui_state: str = "disconnected"
    learning_enabled: bool = False
    prompt_workspace_state: Optional["PromptWorkspaceState"] = None
    resources: Dict[str, List[Any]] = field(
        default_factory=lambda: {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
        }
    )
    queue_items: List[str] = field(default_factory=list)
    running_job: dict[str, Any] | None = None
    queue_status: str = "idle"
    history_items: list[JobHistoryEntry] = field(default_factory=list)
    run_config: Dict[str, Any] = field(default_factory=dict)
    current_config: CurrentConfig = field(default_factory=CurrentConfig)
    _resource_listeners: List[Callable[[Dict[str, List[Any]]], None]] = field(default_factory=list)
    job_draft: JobDraft = field(default_factory=JobDraft)
    lora_strengths: list[LoraRuntimeConfig] = field(default_factory=list)
    adetailer_models: list[str] = field(default_factory=list)
    adetailer_detectors: list[str] = field(default_factory=list)
    adetailer_enabled: bool = False
    adetailer_config: dict[str, Any] = field(default_factory=dict)
    collapse_states: dict[str, bool] = field(default_factory=dict)

    # PR-111: Run Controls UX state flags
    is_run_in_progress: bool = False
    is_direct_run_in_progress: bool = False
    is_queue_paused: bool = False
    last_run_job_id: Optional[str] = None
    last_error_message: Optional[str] = None

    # PR-203: Auto-run queue flag
    auto_run_queue: bool = False

    def set_invoker(self, invoker: GuiInvoker) -> None:
        """Set an invoker used to marshal notifications onto the GUI thread."""
        self._invoker = invoker

    def disable_notifications(self) -> None:
        """Stop delivering listener callbacks (used during teardown)."""
Looking for PackJobEntry definition
I need to find the definition for PackJobEntry. This might be key to understanding how the process is working (or not working) with adding jobs to the queue. I'll track down where it's defined and see if it helps clarify anything in the logic.

Finding PackJobEntry class definition
for i,l in enumerate(txt_state.splitlines()):
    if "class PackJobEntry" in l:
        print(i+1, l)
        print("\n".join(txt_state.splitlines()[i:i+20]))

21 class PackJobEntry:
class PackJobEntry:
    pack_id: str
    pack_name: str
    config_snapshot: dict[str, Any]  # includes randomization-related fields
    prompt_text: str | None = None
    negative_prompt_text: str | None = None
    stage_flags: dict[str, bool] = field(default_factory=dict)
    randomizer_metadata: dict[str, Any] | None = None

@dataclass
class JobDraft:
    packs: list[PackJobEntry] = field(default_factory=list)


@dataclass
class CurrentConfig:
    """Lightweight facade for the currently selected run configuration."""

    preset_name: str = ""
    model_name: str = ""
Exploring PackJobEntry structure and population
Looks like PackJobEntry now includes fields like prompt_text and stage_flags, likely from previous updates. CODEX's issue about sparse metadata might no longer apply. I'll need to investigate how these entries are populated, especially in the app_controller method on_pipeline_add_packs_to_job.

Identifying entry population in pipeline functions
for i,l in enumerate(txt_app.splitlines()):
    if "add_packs_to_job_draft" in l or "on_pipeline_add_packs_to_job" in l:
        print(i+1, l)

2710     def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
2742             self.app_state.add_packs_to_job_draft(entries)
Inspecting app controller entry population and metadata
print("\n".join(txt_app.splitlines()[2700:2755]))

            self._append_log("[controller] No current config to save as preset")
            return False
        success = self._config_manager.save_preset(preset_name, payload)
        if success:
            self._append_log(f"[controller] Preset '{preset_name}' saved")
        else:
            self._append_log(f"[controller] Failed to save preset '{preset_name}'")
        return success

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        """Add one or more packs to the current job draft."""
        self._append_log(f"[controller] Adding packs to job: {pack_ids}")
        
        entries = []
        stage_flags = self._build_stage_flags()
        randomizer_metadata = self._build_randomizer_metadata()
        for pack_id in pack_ids:
            pack = self._find_pack_by_id(pack_id)
            if pack is None:
                self._append_log(f"[controller] Pack not found: {pack_id}")
                continue
            
            # Get current run config from app_state
            run_config = self._run_config_with_lora()
            
            # Ensure randomization is included
            if "randomization_enabled" not in run_config:
                run_config["randomization_enabled"] = self.state.current_config.randomization_enabled
            prompt_text, negative_prompt_text = self._read_pack_prompts(pack)
            entry = PackJobEntry(
                pack_id=pack_id,
                pack_name=pack.name,
                config_snapshot=run_config,
                prompt_text=prompt_text,
                negative_prompt_text=negative_prompt_text,
                stage_flags=dict(stage_flags),
                randomizer_metadata=randomizer_metadata,
            )
            entries.append(entry)
        
        if entries and self.app_state:
            self.app_state.add_packs_to_job_draft(entries)
            self._append_log(f"[controller] Added {len(entries)} pack(s) to job draft")

    def on_add_job_to_queue(self) -> None:
        """Enqueue the current job draft."""
        job = self._build_job_from_draft()
        if job is None:
            return
        if not self.job_service:
            return
        self.job_service.enqueue(job)
        payload = job.payload if isinstance(job.payload, dict) else {}
        packs = payload.get("packs", [])
        pack_count = len(packs) if isinstance(packs, list) else 0
Seeking _build_stage_flags and _build_randomizer_metadata
I need to get the definitions or details for _build_stage_flags and _build_randomizer_metadata. These seem to be critical parts for understanding how the system configures certain behaviors, and knowing their structure will help further clarify the implementation and processing logic around them.

Extracting function definitions from text
for name in ["_build_stage_flags","_build_randomizer_metadata","_run_job","_build_job_from_draft"]:
    if name in txt_app:
        print("==",name,"==")
        loc = txt_app.index(f"def {name}")
        print("\n".join(txt_app.splitlines()[loc//len('') if False else 0:][:3]))

== _build_stage_flags ==
"""
StableNew - App Controller (Skeleton + CancelToken + Worker Thread Stub)

== _build_randomizer_metadata ==
"""
StableNew - App Controller (Skeleton + CancelToken + Worker Thread Stub)

== _run_job ==
---------------------------------------------------------------------------
ValueError                                Traceback (most recent call last)
Cell In[49], line 4
      2 if name in txt_app:
      3     print("==",name,"==")
----> 4     loc = txt_app.index(f"def {name}")
      5     print("\n".join(txt_app.splitlines()[loc//len('') if False else 0:][:3]))

ValueError: substring not found
Fixing snippet printing with manual search
I realize I made a mistake with how I printed the snippet. Instead of relying on the automated process, I'll just manually search through the lines to find the definitions I need. It's a bit more time-consuming, but it should help me get the correct results!

Searching for specific definitions in code
for i,l in enumerate(lines):
    if "_build_stage_flags" in l or "_build_randomizer_metadata" in l or "def _run_job" in l or "def _build_job_from_draft" in l:
        print(i+1, l)

381     def _build_stage_flags(self) -> dict[str, bool]:
401     def _build_randomizer_metadata(self) -> dict[str, Any]:
2568     def _build_job_from_draft(self) -> Job | None:
2715         stage_flags = self._build_stage_flags()
2716         randomizer_metadata = self._build_randomizer_metadata()
Manually printing lines for search definitions
print("\n".join(lines[380:415]))

    def _build_stage_flags(self) -> dict[str, bool]:
        defaults = {"txt2img": True, "img2img": False, "adetailer": True, "upscale": False}
        stage_flags: dict[str, bool] = dict(defaults)
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is not None:
            for stage in ("txt2img", "img2img", "adetailer", "upscale"):
                value = getattr(pipeline_tab, f"{stage}_enabled", None)
                if hasattr(value, "get"):
                    try:
                        stage_flags[stage] = bool(value.get())
                        continue
                    except Exception:
                        pass
                if isinstance(value, bool):
                    stage_flags[stage] = value
        # Include derived refiner/hires flags based on current config
        stage_flags.setdefault("refiner", bool(self.state.current_config.refiner_enabled))
        stage_flags.setdefault("hires", bool(self.state.current_config.hires_enabled))
        return stage_flags

    def _build_randomizer_metadata(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.state.current_config.randomization_enabled),
            "max_variants": max(1, int(self.state.current_config.max_variants or 1)),
        }

    def _read_pack_prompts(self, pack: PromptPackInfo) -> tuple[str, str]:
        try:
            prompts = read_prompt_pack(pack.path)
        except Exception:
            prompts = []
        if not prompts:
            return "", ""
        first = prompts[0]
        return first.get("positive", "").strip(), first.get("negative", "").strip()
Looking for _build_job_from_draft
I need to check out the definition or implementation for _build_job_from_draft. This could be important for what I’m working on, so I’ll go ahead and search for it directly. I want to make sure I’m using the correct breakdown for this specific function or method.

Displaying _build_job_from_draft contents
print("\n".join(lines[2560:2635]))

            return None
        payload = {}
        for config in self.app_state.lora_strengths:
            if config.name:
                payload[config.name] = config.to_dict()
        return payload or None

    def _build_job_from_draft(self) -> Job | None:
        if not self.app_state:
            self._append_log("[controller] Cannot build job - AppState missing.")
            return None
        if not self.app_state.job_draft.packs:
            self._append_log("[controller] Job draft is empty, skipping queue action.")
            return None
        job = Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=None,
            payload=self._job_payload_from_draft(),
            lora_settings=self._lora_settings_payload(),
        )
        return job

    def _job_payload_from_draft(self) -> dict[str, Any]:
        if not self.app_state:
            return {}
        packs = [
            {
                "pack_id": entry.pack_id,
                "pack_name": entry.pack_name,
                "config_snapshot": entry.config_snapshot,
            }
            for entry in self.app_state.job_draft.packs
        ]
        payload = {"packs": packs, "run_config": self._run_config_with_lora()}
        return payload

    def get_lora_runtime_settings(self) -> list[dict[str, Any]]:
        if not self.app_state:
            return []
        return [cfg.to_dict() for cfg in self.app_state.lora_strengths]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = float(strength)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, strength=normalized, enabled=True))
        self.app_state.set_lora_strengths(updated)

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, enabled=normalized))
        self.app_state.set_lora_strengths(updated)


    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
Continuing with _build_job_from_draft
I’m scrolling through the _build_job_from_draft segment a bit more to gather more details. It’s important I check the context fully to understand its functionality. I’ll keep going until I feel I’ve gotten everything I need from this part to proceed effectively.

Displaying _build_job_from_draft segment lines
print("\n".join(lines[2620:2705]))

        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, enabled=normalized))
        self.app_state.set_lora_strengths(updated)


    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
        """Load a pack's config into the stage cards."""
        self._append_log(f"[controller] Loading config for pack: {pack_id}")
        
        # Try to load pack config via ConfigManager
        pack_config = self._config_manager.load_pack_config(pack_id)
        if pack_config is None:
            self._append_log(f"[controller] No config found for pack: {pack_id}")
            return
        pipeline_section = pack_config.get("pipeline") or {}
        self._apply_pipeline_stage_flags(pipeline_section)
        
        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(pack_config)
            self._maybe_set_app_state_lora_strengths(pack_config)
            self._apply_randomizer_from_config(pack_config)
        
        # Update stage cards if available
        pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
            try:
                pipeline_config_panel.apply_run_config(pack_config)
            except Exception as e:
                self._append_log(f"[controller] Error applying pack config to stages: {e}")
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, pack_config)
            stage_panel.load_adetailer_config(pack_config.get("adetailer") or {})
        self._apply_adetailer_config_section(pack_config)
        
        self._append_log(f"[controller] Loaded config for pack '{pack_id}'")

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        """Write current stage config into one or more packs."""
        self._append_log(f"[controller] Applying config to packs: {pack_ids}")
        
        # Get current run config
        current_config = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            current_config.update(panel_randomizer)
        if not current_config:
            self._append_log("[controller] No current config to apply")
            return
        if self.app_state:
            self.app_state.set_run_config(current_config)
        
        # Save to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, current_config)
            if success:
                self._append_log(f"[controller] Applied config to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply config to pack '{pack_id}'")

    def save_current_pipeline_preset(self, preset_name: str) -> bool:
        """Persist the current pipeline/stage config as a named preset."""
        self._append_log(f"[controller] Saving current pipeline config as preset '{preset_name}'")
        payload = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            payload.update(panel_randomizer)
        if not payload:
            self._append_log("[controller] No current config to save as preset")
            return False
        success = self._config_manager.save_preset(preset_name, payload)
        if success:
            self._append_log(f"[controller] Preset '{preset_name}' saved")
Expanding view of _build_job_from_draft
I truncated the _build_job_from_draft earlier, so now I’ll focus on displaying the lines around line 2568 more thoroughly. I need to review this section more carefully to fully understand how it fits into what I’m working on. Let’s ensure I get a clearer picture this time.

Displaying truncated lines from code
print("\n".join(lines[2568:2625]))

        if not self.app_state:
            self._append_log("[controller] Cannot build job - AppState missing.")
            return None
        if not self.app_state.job_draft.packs:
            self._append_log("[controller] Job draft is empty, skipping queue action.")
            return None
        job = Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=None,
            payload=self._job_payload_from_draft(),
            lora_settings=self._lora_settings_payload(),
        )
        return job

    def _job_payload_from_draft(self) -> dict[str, Any]:
        if not self.app_state:
            return {}
        packs = [
            {
                "pack_id": entry.pack_id,
                "pack_name": entry.pack_name,
                "config_snapshot": entry.config_snapshot,
            }
            for entry in self.app_state.job_draft.packs
        ]
        payload = {"packs": packs, "run_config": self._run_config_with_lora()}
        return payload

    def get_lora_runtime_settings(self) -> list[dict[str, Any]]:
        if not self.app_state:
            return []
        return [cfg.to_dict() for cfg in self.app_state.lora_strengths]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = float(strength)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled))
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, strength=normalized, enabled=True))
        self.app_state.set_lora_strengths(updated)

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
Clarifying PR structure and task scope
The _job_payload_from_draft relies on job_draft.packs, which should now include prompts and stage_flags. Given the new V2 pipeline path, we may not need changes but need to keep in mind potential legacy paths. Since the user wants minimal PRs, I'll likely structure the first as "PR-0129-A Core Run Path & Runner DI Consolidation."

Clarifying user request and PR naming convention
The user asked for a "Core Run Path & Runner DI" as PR-A, and "GUI Job Wiring" as PR-B. While they didn't assign numeric IDs, I can use PR-0129A and PR-0129B for now, though these names may be placeholders. I'll follow the user's request but provide the flexibility to assign numbers later.

Generating PR-A and PR-B templates for review
with open(os.path.join(base,"PR_TEMPLATE_v2.5.md"),"r") as f:
    tmpl = f.read()
print("\n".join(tmpl.splitlines()[:40]))

#CANONICAL
PR-### — Title of Change (V2.5)

Discovery Reference: D-##
Date: YYYY-MM-DD HH:MM (local time)
Author: <Name or AI Agent>

1. Summary (Executive Abstract)

Provide a concise, high-level description (4–7 sentences):

What the PR does

Why it exists

Which subsystems it affects

What changes for the user and/or system

What risks or considerations exist

This must be a standalone EXSUM.

2. Motivation / Problem Statement

Describe:

The current behavior

Why it is incorrect or insufficient

Evidence (errors, UX issues, architectural violations, failing tests)

Consequences of not fixing

Why solving this now matters in the roadmap

Do not propose the solution here—state the pain, not the fix.

3. Scope & Non-Goals
Extracting key headings from text
for i,l in enumerate(tmpl.splitlines()):
    if l.strip().startswith("1.") or l.strip().startswith("2.") or l.strip().startswith("13."):
        print(i+1,l)

8 1. Summary (Executive Abstract)
24 2. Motivation / Problem Statement
260 13. Potential Pitfalls (LLM Guidance)
Building the new document structure
I think it's easier to stick with the existing structure for now. I'll build the new documents manually, reusing it, which will streamline things. The template probably follows 14 sections, so I should take a look at the end to ensure it's aligned with what we need.

Viewing last 60 lines of template structure
print("\n".join(tmpl.splitlines()[-60:]))

Does it alter queue, randomizer, or controller semantics?

Does it modify run modes or job lifecycle?

Does it update UX or GUI layout?

Does it modify developer workflow, PR flow, or governance?

11.2 Mapping to Required Docs
If Yes In…	Update:
Subsystem behavior	ARCHITECTURE_v2.5.md
Responsibilities	ARCHITECTURE_v2.5.md
Queue / Randomizer / Job lifecycle	Module specs (randomizer, learning, cluster)
UX / GUI	ROADMAP_v2.5.md
Development workflow	GOVERNANCE_v2.5.md
11.3 CHANGELOG.md Entry (Required)

Each PR must append:

## [PR-###] - YYYY-MM-DD HH:MM
Summary: <short EXSUM>
Files Modified:
- <file> : <short desc>
- <file> : <short desc>
Canonical Docs Updated:
- ARCHITECTURE_v2.5.md (section 3.2 updated)
- ROADMAP_v2.5.md (queue plan clarified)
Notes:
<optional>

12. Rollback Plan
12.1 Rollback Specification Matrix
Category	Items
Files to revert	…
Files to delete	…
Tests to revert	…
Tests to delete	…
Doc updates to undo	…
Expected behavior after rollback	…
13. Potential Pitfalls (LLM Guidance)

List foreseeable mistakes the LLM/Copilot must avoid.

Example:

Do not add new cross-layer imports

Do not modify forbidden files

Do not alter default run modes unless required

Do not create circular imports

Do not change pipeline-builder semantics unless explicitly stated

14. Additional Notes / Assumptions

Optional free-form notes.

✔ End of PR Template (Canonical V2.5)
Designing PR-A and PR-B with concrete details
Now that I've gathered enough context on the repo, I need to design PR-A and PR-B more concretely. I'll reference actual classes and functions, ensuring dependency injection (DI) is applied properly. The goal is to get the pipeline working with just two PRs. I'll focus on key components like the GUI panels, controllers, and job runners. There may be some integration tests too, but DI-level tests should be prioritized. Next, I'll check the submit_preview_jobs_to_queue implementation to confirm the run path.

Searching for submit_preview_jobs_to_queue implementation
for i,l in enumerate(txt_pc.splitlines()):
    if "submit_preview_jobs_to_queue" in l:
        print(i+1, l)

834     def submit_preview_jobs_to_queue(
Designing PR-A and PR-B architecture
print("\n".join(txt_pc.splitlines()[830:880]))

        result = runner.run(job.pipeline_config, self.cancel_token)
        return result.to_dict() if hasattr(result, 'to_dict') else {"result": result}

    def submit_preview_jobs_to_queue(
        self,
        *,
        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data."""
        normalized_jobs = self.get_preview_jobs()
        if not normalized_jobs:
            return 0

        submitted = 0
        for record in normalized_jobs:
            prompt_pack_id = None
            config = record.config
            if isinstance(config, dict):
                prompt_pack_id = config.get("prompt_pack_id")
            job = self._to_queue_job(
                record,
                run_mode="queue",
                source=source,
                prompt_source=prompt_source,
                prompt_pack_id=prompt_pack_id,
            )
            job.payload = lambda j=job: self._run_job(j)
            self._job_service.submit_job_with_run_mode(job)
            submitted += 1
        return submitted

    def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            result = runner.run(config, self.cancel_token)
        self.record_run_result(result)
        return result

    def get_job_history_service(self) -> JobHistoryService | None:
        """Return a JobHistoryService bound to this controller's queue/history."""

        if self._job_history_service is None:
            try:
                queue = self._job_controller.get_queue()
Displaying truncated function code
print("\n".join(txt_pc.splitlines()[836:870]))

        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data."""
        normalized_jobs = self.get_preview_jobs()
        if not normalized_jobs:
            return 0

        submitted = 0
        for record in normalized_jobs:
            prompt_pack_id = None
            config = record.config
            if isinstance(config, dict):
                prompt_pack_id = config.get("prompt_pack_id")
            job = self._to_queue_job(
                record,
                run_mode="queue",
                source=source,
                prompt_source=prompt_source,
                prompt_pack_id=prompt_pack_id,
            )
            job.payload = lambda j=job: self._run_job(j)
            self._job_service.submit_job_with_run_mode(job)
            submitted += 1
        return submitted

    def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
Reviewing _to_queue_job and _run_job
I need to check the functions _to_queue_job and _run_job to fully understand their role in the pipeline. This will help confirm how jobs are processed and identify any areas that need work or alignment with the current design before proceeding with further development.

Identifying _to_queue_job and _run_job functions
for i,l in enumerate(txt_pc.splitlines()):
    if "def _to_queue_job" in l or "def _run_job" in l:
        print(i+1, l)

284     def _to_queue_job(
824     def _run_job(self, job: Job) -> dict[str, Any]:
Extracting specific lines from text output
print("\n".join(txt_pc.splitlines()[276:312]))

        """Return normalized jobs derived from the current GUI state for preview panels."""
        try:
            return self._build_normalized_jobs_from_state()
        except Exception as exc:
            _logger.debug("Failed to build preview jobs: %s", exc)
            return []

    def _to_queue_job(
        self,
        record: NormalizedJobRecord,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
    ) -> Job:
        """Convert a NormalizedJobRecord into the Job model used by JobService.

        This adapter preserves all metadata from the normalized record
        while producing a Job compatible with the existing queue system.
        """
        # Get config snapshot from normalized record
        config_snapshot = record.to_queue_snapshot()

        # Extract pipeline_config from record.config if it's the right type
        pipeline_config = None
        if isinstance(record.config, PipelineConfig):
            pipeline_config = record.config
        elif hasattr(record.config, "__dict__"):
            # Try to construct PipelineConfig from dict-like object
            try:
                pipeline_config = record.config
            except Exception:
                pass

        # Build randomizer metadata from record
Displaying selected code lines
print("\n".join(txt_pc.splitlines()[312:360]))

        randomizer_metadata = record.randomizer_summary

        return Job(
            job_id=record.job_id,
            pipeline_config=pipeline_config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            randomizer_metadata=randomizer_metadata,
            variant_index=record.variant_index,
            variant_total=record.variant_total,
            learning_enabled=self._learning_enabled,
        )

    def start_pipeline_v2(
        self,
        *,
        run_mode: str | None = None,
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Start pipeline using V2 job building via JobBuilderV2.

        This is the new V2 run entrypoint that:
        1. Builds normalized jobs via JobBuilderV2
        2. Converts them to queue Jobs
        3. Submits via JobService respecting run_mode

        Args:
            run_mode: Force "direct" or "queue". If None, uses state.
            source: Job source for provenance (e.g., "gui", "api").
            prompt_source: Prompt source type (e.g., "manual", "pack").
            prompt_pack_id: Optional prompt pack ID if using packs.
            on_complete: Callback on successful completion.
            on_error: Callback on error.

        Returns:
            True if jobs were submitted, False otherwise.
        """
        if not self.state_manager.can_run():
            return False

Displaying specific lines from text
print("\n".join(txt_pc.splitlines()[820:842]))


            self._job_service.submit_job_with_run_mode(job)

    def _run_job(self, job: Job) -> dict[str, Any]:
        """Run a single job."""
        if not job.pipeline_config:
            return {"error": "No pipeline config"}
        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        structured_logger = StructuredLogger()
        runner = PipelineRunner(api_client, structured_logger)
        result = runner.run(job.pipeline_config, self.cancel_token)
        return result.to_dict() if hasattr(result, 'to_dict') else {"result": result}

    def submit_preview_jobs_to_queue(
        self,
        *,
        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data."""
        normalized_jobs = self.get_preview_jobs()
        if not normalized_jobs:
Clarifying _run_job behavior and job runners
So, _run_job creates a new PipelineRunner with an SDWebUIClient per job, which could be fine, though it doesn’t seem to reuse the runner DI though. JobService uses runner.run_once(job) and executes job.payload, which appears to reflect that runner just runs the job in the same thread. I need to understand if SingleNodeJobRunner expects job.payload as a dict or a function. Let's look at that.

Analyzing job runner behavior and payload handling
with open(os.path.join(extract_dir,"src","queue","single_node_runner.py"),"r") as f:
    print("".join(f.readlines()[60:160]))

                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    result = self.run_callable(job)
                else:
                    result = {}
                self.job_queue.mark_completed(job.job_id, result=result)
                self._notify(job, JobStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            if self.run_callable:
                result = self.run_callable(job)
            else:
                result = {}
            self.job_queue.mark_completed(job.job_id, result=result)
            self._notify(job, JobStatus.COMPLETED)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

Inspecting SingleNodeJobRunner's behavior
I see that SingleNodeJobRunner uses a run_callable passed at construction and doesn’t directly call job.payload. JobService likely passes this run_callable, so it’s worth inspecting that connection and how it works. I need to understand how that interacts with job.payload in practice.

Inspecting usage of run_callable in JobService
for i,l in enumerate(txt_app.splitlines()):
    if "job_service =" in l:
        print(i+1, l)

Checking for all job_service instances
Alright, I need to search for all occurrences of job_service across the source code. That's important to make sure I’m understanding how it’s being used, and to ensure that I’m not missing any relevant parts of the code that interact with this service. Let's look for them carefully.

Counting job_service occurrences in source files
matches = []
for root,dirs,files in os.walk(os.path.join(extract_dir,"src")):
    for fn in files:
        if fn.endswith(".py"):
            path = os.path.join(root,fn)
            with open(path,"r",errors="ignore") as f:
                if "JobService(" in f.read():
                    matches.append(path)
matches
['/mnt/data/repo/src/controller/app_controller.py',
 '/mnt/data/repo/src/controller/pipeline_controller.py']
Searching for JobService occurrences in files
for path in matches:
    print("==", path, "==")
    with open(path,"r",errors="ignore") as f:
        for line in f:
            if "JobService(" in line:
                print(line.strip())

== /mnt/data/repo/src/controller/app_controller.py ==
return JobService(
== /mnt/data/repo/src/controller/pipeline_controller.py ==
else JobService(queue, runner, history_store, history_service=history_service)
Finding job_service occurrences in source code
with open(os.path.join(extract_dir,"src","controller","app_controller.py"),"r") as f:
    txt_app = f.read()
loc = txt_app.index("JobService(")
print("\n".join(txt_app.splitlines()[loc//100:loc//100+40]))

    def __init__(
        self,
        main_window: MainWindow | None,
        pipeline_runner: Optional[PipelineRunner] = None,
        threaded: bool = True,
        packs_dir: Path | str | None = None,
        api_client: SDWebUIClient | None = None,
        structured_logger: StructuredLogger | None = None,
        webui_process_manager: WebUIProcessManager | None = None,
        config_manager: ConfigManager | None = None,
        resource_service: WebUIResourceService | None = None,
        job_service: JobService | None = None,
        pipeline_controller: PipelineController | None = None,
    ) -> None:
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        self.state = AppState()
        self.threaded = threaded
        self._config_manager = config_manager or ConfigManager()
        self._dropdown_loader = DropdownLoader(self._config_manager)
        self._last_executor_config: dict[str, Any] | None = None
        self._last_run_snapshot: dict[str, Any] | None = None
        self._last_run_auto_restored = False
        self._last_run_store = LastRunStoreV2_5()

        if pipeline_runner is not None:
            self.pipeline_runner = pipeline_runner
            # Still set api_client and structured_logger for PipelineController
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
        else:
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = PipelineRunner(self._api_client, self._structured_logger)

        self._webui_api: WebUIAPI | None = None

        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
Finding where job_service is assigned
I need to track down the location where job_service is assigned. This will help in understanding how it's set up and where it’s initialized. It's key to ensure everything is connected correctly and nothing's missed. Let's locate that assignment carefully.

Finding job_service assignment locations
for i,l in enumerate(lines := txt_app.splitlines()):
    if "self.job_service" in l and " = " in l:
        print(i+1, l)

277         self.job_service = job_service or self._build_job_service()
953         queue = getattr(self.job_service, "queue", None)
965         queue = getattr(self.job_service, "queue", None)
977         queue = getattr(self.job_service, "queue", None)
989         queue = getattr(self.job_service, "queue", None)
1004             queue = getattr(self.job_service, "queue", None)
1014             queue = getattr(self.job_service, "queue", None)
1024             queue = getattr(self.job_service, "queue", None)
1032             queue = getattr(self.job_service, "queue", None)
1039             queue = getattr(self.job_service, "queue", None)
1046             queue = getattr(self.job_service, "queue", None)
1061             queue = getattr(self.job_service, "queue", None)
1078         queue = getattr(self.job_service, "queue", None)
1091         store = getattr(self.job_service, "history_store", None)
Extracting job_service assignment area
print("\n".join(lines[260:300]))

            self._structured_logger = structured_logger or StructuredLogger()
        else:
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = PipelineRunner(self._api_client, self._structured_logger)

        self._webui_api: WebUIAPI | None = None

        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
        self.webui_process_manager = webui_process_manager
        self._cancel_token: Optional[CancelToken] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._packs_dir = Path(packs_dir) if packs_dir is not None else Path("packs")
        self._job_history_path = Path("runs") / "job_history.json"
        self.job_service = job_service or self._build_job_service()
        self._is_shutting_down = False
        self._shutdown_started_at: float | None = None
        self._shutdown_completed = False
        self.packs: list[PromptPackInfo] = []
        self._selected_pack_index: Optional[int] = None

        # Initialize PipelineController for modern pipeline execution (bridge)
        self.pipeline_controller = pipeline_controller or PipelineController(
            api_client=self._api_client,
            structured_logger=self._structured_logger,
            job_service=self.job_service,
            pipeline_runner=self.pipeline_runner,
        )

        # Wire GUI overrides into PipelineController so config assembler can access GUI state
        self.pipeline_controller.get_gui_overrides = self._get_gui_overrides_for_pipeline  # type: ignore[attr-defined]

        # GUI log handler for LogTracePanelV2
        self.gui_log_handler = InMemoryLogHandler(max_entries=500, level=logging.INFO)
        root_logger = logging.getLogger()
        if root_logger.level > logging.INFO or root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self.gui_log_handler)
Looking for _build_job_service function
I haven't come across the _build_job_service function yet. It’s probably important for understanding the setup of the job service, so I’ll need to locate it. Let me search for that function to ensure it's properly included in the flow and everything's connected.

Finding _build_job_service function in code
for i,l in enumerate(lines):
    if "def _build_job_service" in l:
        print(i+1, l)
        print("\n".join(lines[i:i+40]))

562     def _build_job_service(self) -> JobService:
    def _build_job_service(self) -> JobService:
        self._job_history_path.parent.mkdir(parents=True, exist_ok=True)
        history_store = JSONLJobHistoryStore(self._job_history_path)
        job_queue = JobQueue(history_store=history_store)
        runner = SingleNodeJobRunner(
            job_queue,
            run_callable=self._execute_job,
            poll_interval=0.05,
        )
        history_service = JobHistoryService(job_queue, history_store)
        return JobService(
            job_queue,
            runner,
            history_store,
            history_service=history_service,
        )

    def _setup_queue_callbacks(self) -> None:
        if not self.job_service:
            return
        self.job_service.register_callback(JobService.EVENT_QUEUE_UPDATED, self._on_queue_updated)
        self.job_service.register_callback(JobService.EVENT_QUEUE_STATUS, self._on_queue_status_changed)
        self.job_service.register_callback(JobService.EVENT_JOB_STARTED, self._on_job_started)
        self.job_service.register_callback(JobService.EVENT_JOB_FINISHED, self._on_job_finished)
        self.job_service.register_callback(JobService.EVENT_JOB_FAILED, self._on_job_failed)
        self.job_service.register_callback(JobService.EVENT_QUEUE_EMPTY, self._on_queue_empty)
        self._refresh_job_history()
        # PR-GUI-F3: Load persisted queue state on startup
        self._load_queue_state()

    # ------------------------------------------------------------------
    # PR-GUI-F3: Queue persistence helpers
    # ------------------------------------------------------------------

    def _load_queue_state(self) -> None:
        """Load persisted queue state on startup.
        
        PR-GUI-F3: Restores queue jobs and control flags from disk.
        """
        snapshot = load_queue_snapshot()
Inspecting _build_job_service and _execute_job
The _build_job_service creates a SingleNodeJobRunner with a run_callable pointing to self._execute_job. This encourages using runner.run_once(job) to call self._execute_job. I need to check out _execute_job within AppController to understand how this all ties together.

Inspecting _execute_job method in AppController
for i,l in enumerate(lines):
    if "def _execute_job" in l:
        print(i+1, l)
        print("\n".join(lines[i:i+40]))

635     def _execute_job(self, job: Job) -> dict[str, Any]:
    def _execute_job(self, job: Job) -> dict[str, Any]:
        self._append_log(f"[queue] Executing job {job.job_id} with payload {job.payload!r}")

        payload = getattr(job, "payload", None)

        if callable(payload):
            try:
                result = payload()
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[queue] Callable payload for job {job.job_id} raised: {exc!r}")
                raise
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "callable",
                "result": result,
            }

        if not isinstance(payload, dict):
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "opaque",
                "payload_type": type(payload).__name__,
            }

        packs = payload.get("packs") or []
        run_config = payload.get("run_config") or {}

        if not packs:
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "prompt_pack_batch",
                "total_entries": 0,
                "results": [],
            }

        results: list[dict[str, Any]] = []
        for idx, pack in enumerate(packs):
Investigating _job payload options
The _job payload can either be a callable or a dictionary. For packing a batch, it seems like the entries are processed through the PipelineController. I should check the rest of the code snippet to confirm how this all operates and how the entries are handled in the packing process.

Displaying specific lines of code snippet
print("\n".join(lines[675:735]))

            pack_name = pack.get("pack_name", "")
            cfg_snapshot = pack.get("config_snapshot") or {}
            variant_index = pack.get("variant_index") or cfg_snapshot.get("variant_index") or idx
            try:
                entry_result = self._execute_pack_entry(
                    pack_id=pack_id,
                    pack_name=pack_name,
                    cfg_snapshot=cfg_snapshot,
                    run_config=run_config,
                    variant_index=variant_index,
                )
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[queue] Error while executing pack {pack_id or pack_name}: {exc!r}")
                entry_result = self._build_pack_result(
                    pack_id=pack_id,
                    pack_name=pack_name,
                    variant_index=variant_index,
                    prompt=cfg_snapshot.get("prompt", ""),
                    negative_prompt=cfg_snapshot.get("negative_prompt", ""),
                    params=self._merge_run_params(cfg_snapshot, run_config),
                    pipeline_mode=None,
                    run_result=None,
                    status="error",
                    error=str(exc),
                )
            results.append(entry_result)

        return {
            "job_id": job.job_id,
            "status": "executed",
            "mode": "prompt_pack_batch",
            "total_entries": len(packs),
            "results": results,
        }

    def _execute_pack_entry(
        self,
        *,
        pack_id: str,
        pack_name: str,
        cfg_snapshot: dict[str, Any],
        run_config: dict[str, Any],
        variant_index: int | None = None,
    ) -> dict[str, Any]:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)

        prompt = self._derive_prompt(cfg_snapshot, run_config)
        negative_prompt = self._derive_negative_prompt(cfg_snapshot, run_config)

        if pipeline_tab and hasattr(pipeline_tab, "prompt_text"):
            try:
                pipeline_tab.prompt_text.delete(0, "end")
                if prompt:
                    pipeline_tab.prompt_text.insert(0, prompt)
            except Exception:
                pass

        self._apply_pipeline_tab_config(pipeline_tab, cfg_snapshot, run_config)

        params = self._merge_run_params(cfg_snapshot, run_config)
Exploring job and pipeline flow
The _execute_pack_entry function uses the pipeline_tab and merges the config, likely calling pipeline_controller.start_pipeline_v2 or run_pipeline. The "Add to Job" button triggers different paths for job management. The preview panel uses normalized jobs built independently, not tied to the job_draft, which leads to some complexity in the pipeline flow. There’s a separate function in PipelineController that creates preview jobs, using pipeline selections instead.

Tracing job preview and pipeline flow
with open(os.path.join(extract_dir,"src","gui","panels_v2","layout_manager_v2.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Optional layout manager to compose V2 panels."""

from __future__ import annotations

from typing import Any

from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame


class LayoutManagerV2:
    """Helper to build and attach panel instances to a main window."""

    def __init__(self, main_window: Any) -> None:
        self.main_window = main_window

    def attach_panels(self) -> None:
        """Instantiate and wire V2 tab frames into the notebook."""
        mw = self.main_window
        notebook = getattr(mw, "center_notebook", None)
        if notebook is None:
            return

        app_state = getattr(mw, "app_state", None)
        app_controller = getattr(mw, "app_controller", None)
        pipeline_controller = getattr(mw, "pipeline_controller", None)
        prompt_workspace_state = getattr(mw, "prompt_workspace_state", None)
        theme = getattr(mw, "theme", None)

        mw.prompt_tab = PromptTabFrame(
            notebook,
            app_state=app_state,
        )
        notebook.add(mw.prompt_tab, text="Prompt")

        mw.pipeline_tab = PipelineTabFrame(
            notebook,
            prompt_workspace_state=prompt_workspace_state,
            app_state=app_state,
            app_controller=app_controller,
            pipeline_controller=pipeline_controller,
            theme=theme,
        )
        notebook.add(mw.pipeline_tab, text="Pipeline")

        mw.learning_tab = LearningTabFrame(
            notebook,
            app_state=app_state,
            pipeline_controller=pipeline_controller,
        )
        notebook.add(mw.learning_tab, text="Learning")

        notebook.select(mw.pipeline_tab)

        if hasattr(mw.pipeline_tab, "pack_loader_compat"):
            mw.left_zone = mw.pipeline_tab.pack_loader_compat
        mw.right_zone = getattr(mw.pipeline_tab, "preview_panel", None)

        mw.sidebar_panel_v2 = getattr(mw.pipeline_tab, "sidebar", None)
        stage_panel = getattr(mw.pipeline_tab, "stage_cards_panel", None)
        mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
        mw.pipeline_panel_v2 = stage_panel
        mw.randomizer_panel_v2 = getattr(mw.pipeline_tab, "randomizer_panel", None)
        mw.preview_panel_v2 = getattr(mw.pipeline_tab, "preview_panel", None)
        mw.status_bar_v2 = getattr(getattr(mw, "bottom_zone", None), "status_bar_v2", None)

        mw.pipeline_controls_panel = getattr(stage_panel, "controls_panel", stage_panel)
        mw.run_pipeline_btn = getattr(stage_panel, "run_button", None)

Reading PipelineTabFrame source code
with open(os.path.join(extract_dir,"src","gui","views","pipeline_tab_frame_v2.py"),"r") as f:
    txt_pipe_tab = f.read()
print(txt_pipe_tab[:260])

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as design_system
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 impo
Searching for preview panel references
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "preview_panel" in l or "PreviewPanelV2" in l:
        print(i+1, l)

11 from src.gui.preview_panel_v2 import PreviewPanelV2
111         self.preview_panel = PreviewPanelV2(
117         self.preview_panel.grid(row=0, column=0, sticky="nsew")
365         if hasattr(self, "preview_panel"):
367                 self.preview_panel.update_from_controls(self.sidebar)
387         if self.app_state is None or not hasattr(self, "preview_panel"):
392                 self.preview_panel.update_from_job_draft(job_draft)
398         if not hasattr(self, "preview_panel"):
404             self.preview_panel.set_jobs(records)
Extracting specific lines from text
print("\n".join(txt_pipe_tab.splitlines()[100:145]))


        self.right_scroll = ScrollableFrame(self.right_column, style=CARD_FRAME_STYLE)
        self.right_scroll.grid(row=0, column=0, sticky="nsew")
        self.right_scroll.inner.columnconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(3, weight=1)  # History row gets weight

        preview_card = _create_card(self.right_scroll.inner)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 8))
        preview_card.rowconfigure(0, weight=1)
        self.preview_panel = PreviewPanelV2(
            preview_card,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.preview_panel.grid(row=0, column=0, sticky="nsew")

        # PR-GUI-F1: Run Controls panel removed - controls moved to QueuePanelV2

        queue_card = _create_card(self.right_scroll.inner)
        queue_card.grid(row=1, column=0, sticky="ew", padx=(0, 12),pady=(0, 8))
        self.queue_panel = QueuePanelV2(
            queue_card,
            controller=queue_controller,
            app_state=self.app_state,
        )
        self.queue_panel.grid(row=0, column=0, sticky="ew")

        running_job_card = _create_card(self.right_scroll.inner)
        running_job_card.grid(row=2, column=0, sticky="ew", padx=(0, 12),pady=(0, 8))
        self.running_job_panel = RunningJobPanelV2(
            running_job_card,
            controller=queue_controller,
            app_state=self.app_state,
        )
        self.running_job_panel.grid(row=0, column=0, sticky="ew")

        history_card = _create_card(self.right_scroll.inner)
        history_card.grid(row=3, column=0, sticky="nsew", padx=(0, 12),pady=(0, 0))
        history_card.rowconfigure(0, weight=1)
        self.history_panel = JobHistoryPanelV2(
            history_card,
            controller=queue_controller,
            app_state=self.app_state,
Considering methods for update_from_controls
I’m thinking I need to create methods like update_from_controls and other similar ones to track changes in the pipeline state. This would allow for smooth updates on the UI or other elements affected by the user controls. This step seems necessary for making the flow work seamlessly.

Extracting methods from control updates
print("\n".join(txt_pipe_tab.splitlines()[360:410]))

                card.grid_remove()

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        if hasattr(self, "preview_panel"):
            try:
                self.preview_panel.update_from_controls(self.sidebar)
            except Exception:
                pass
        self._refresh_preview_from_pipeline_jobs()

    def _on_restore_last_run_clicked(self) -> None:
        controller = self.app_controller or self.pipeline_controller
        if not controller:
            return
        try:
            controller.restore_last_run(force=True)
        except Exception:
            pass

    def _on_app_state_resources_changed(self, resources: dict[str, list[Any]] | None = None) -> None:
        panel = getattr(self, "stage_cards_panel", None)
        if panel is not None and resources:
            panel.apply_resource_update(resources)

    def _on_job_draft_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "preview_panel"):
            return
        try:
            job_draft = self.app_state.job_draft
            if not self._refresh_preview_from_pipeline_jobs():
                self.preview_panel.update_from_job_draft(job_draft)
        except Exception:
            pass

    def _refresh_preview_from_pipeline_jobs(self) -> bool:
        """Attempt to render JobUiSummary data before falling back to draft text."""
        if not hasattr(self, "preview_panel"):
            return False
        records = self._get_pipeline_preview_jobs()
        if not records:
            return False
        try:
            self.preview_panel.set_jobs(records)
            return True
        except Exception:
            return False

    def _get_pipeline_preview_jobs(self) -> list[NormalizedJobRecord]:
        controller = self.pipeline_controller or getattr(self.app_controller, "pipeline_controller", None)
Retrieving code snippet for methods update_from_controls
print("\n".join(txt_pipe_tab.splitlines()[387:430]))

            return
        try:
            job_draft = self.app_state.job_draft
            if not self._refresh_preview_from_pipeline_jobs():
                self.preview_panel.update_from_job_draft(job_draft)
        except Exception:
            pass

    def _refresh_preview_from_pipeline_jobs(self) -> bool:
        """Attempt to render JobUiSummary data before falling back to draft text."""
        if not hasattr(self, "preview_panel"):
            return False
        records = self._get_pipeline_preview_jobs()
        if not records:
            return False
        try:
            self.preview_panel.set_jobs(records)
            return True
        except Exception:
            return False

    def _get_pipeline_preview_jobs(self) -> list[NormalizedJobRecord]:
        controller = self.pipeline_controller or getattr(self.app_controller, "pipeline_controller", None)
        if controller is None:
            return []
        getter = getattr(controller, "get_preview_jobs", None)
        if not callable(getter):
            return []
        try:
            return getter()
        except Exception:
            return []

    def _on_queue_items_changed(self) -> None:
        if self.app_state is None:
            return
        # PR-GUI-F1: Queue items are now displayed in QueuePanelV2
        try:
            if hasattr(self, "queue_panel"):
                self.queue_panel.update_from_app_state(self.app_state)
        except Exception:
            pass

Investigating preview panel and updates
The preview panel relies on methods like update_from_controls, update_from_job_draft, and set_jobs. Currently, the pipeline tab updates from the pipeline jobs when job draft changes but falls back to the draft view. I suspect the critique about the preview not seeing normalized jobs might be due to a bug in the pipeline controller’s build_normalized_jobs_from_state. I’ll need to inspect that function.

Inspecting pipeline controller functions for job normalization
for i,l in enumerate(txt_pc.splitlines()):
    if "_build_normalized_jobs_from_state" in l or "get_preview_jobs" in l:
        print(i+1, l)

187     def _build_normalized_jobs_from_state(
276     def get_preview_jobs(self) -> list[NormalizedJobRecord]:
279             return self._build_normalized_jobs_from_state()
384             normalized_jobs = self._build_normalized_jobs_from_state()
841         normalized_jobs = self.get_preview_jobs()
Inspecting pipeline controller normalized jobs logic
print("\n".join(txt_pc.splitlines()[180:220]))

        )

    # -------------------------------------------------------------------------
    # V2 Job Building via JobBuilderV2 (PR-204C)
    # -------------------------------------------------------------------------

    def _build_normalized_jobs_from_state(
        self,
        base_config: PipelineConfig | None = None,
    ) -> list[NormalizedJobRecord]:
        """Build fully-normalized jobs from current GUI/AppState.

        This is the single entrypoint for V2 job construction.
        All run entrypoints should call this helper.

        Args:
            base_config: Optional pre-built PipelineConfig.
                If None, builds from current state.

        Returns:
            List of NormalizedJobRecord instances ready for queue/preview.
        """
        # Build base config if not provided
        if base_config is None:
            try:
                base_config = self._build_pipeline_config_from_state()
            except Exception as exc:
                _logger.warning("Failed to build pipeline config: %s", exc)
                return []

        # Extract randomization plan from state if available
        randomization_plan = None
        try:
            rand_meta = self._extract_metadata("randomizer_metadata")
            if rand_meta and rand_meta.get("enabled"):
                from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
                seed_mode_str = rand_meta.get("seed_mode", "FIXED")
                try:
                    seed_mode = RandomizationSeedMode[seed_mode_str.upper()]
                except (KeyError, AttributeError):
Inspecting pipeline normalization and job preview behavior
print("\n".join(txt_pc.splitlines()[220:280]))

                    seed_mode = RandomizationSeedMode.FIXED

                randomization_plan = RandomizationPlanV2(
                    enabled=True,
                    model_choices=rand_meta.get("model_choices", []),
                    sampler_choices=rand_meta.get("sampler_choices", []),
                    cfg_scale_values=rand_meta.get("cfg_scale_values", []),
                    steps_values=rand_meta.get("steps_values", []),
                    seed_mode=seed_mode,
                    base_seed=rand_meta.get("base_seed"),
                    max_variants=rand_meta.get("max_variants", 0),
                )
        except Exception as exc:
            _logger.debug("Could not extract randomization plan: %s", exc)

        # Extract batch settings from state
        batch_settings = BatchSettings()
        try:
            overrides = self._extract_state_overrides()
            batch_size = getattr(overrides, "batch_size", 1) or 1
            batch_runs = getattr(self.state_manager, "batch_runs", 1) or 1
            batch_settings = BatchSettings(batch_size=batch_size, batch_runs=batch_runs)
        except Exception as exc:
            _logger.debug("Could not extract batch settings: %s", exc)

        # Extract output settings from state
        output_settings = OutputSettings()
        try:
            overrides = self._extract_state_overrides()
            output_dir = getattr(overrides, "output_dir", "") or "output"
            filename_pattern = getattr(overrides, "filename_pattern", "") or "{seed}"
            output_settings = OutputSettings(
                base_output_dir=output_dir,
                filename_template=filename_pattern,
            )
        except Exception as exc:
            _logger.debug("Could not extract output settings: %s", exc)

        # Build jobs via JobBuilderV2
        try:
            jobs = self._job_builder.build_jobs(
                base_config=base_config,
                randomization_plan=randomization_plan,
                batch_settings=batch_settings,
                output_settings=output_settings,
            )
        except Exception as exc:
            _logger.warning("JobBuilderV2 failed to build jobs: %s", exc)
            return []

        if not jobs:
            _logger.warning("JobBuilderV2 returned no jobs for current state")

        return jobs

    def get_preview_jobs(self) -> list[NormalizedJobRecord]:
        """Return normalized jobs derived from the current GUI state for preview panels."""
        try:
            return self._build_normalized_jobs_from_state()
        except Exception as exc:
Solidifying run path for job service
It looks like jobs are being built from the current GUI/AppState, not the job_draft, which should be okay. For the tasks at hand, my focus is to solidify the core run path:

Make sure AppController’s _build_job_service uses JobService with dependency injection.

Ensure JobService utilizes SingleNodeJobRunner with a specific run callable.

Unify PipelineController’s _run_job using a pipeline runner.

Ensure stable history integration and tests that use a stub runner to prevent actual WebUI calls. I should check out the existing stub_runner.py.

Inspecting stub_runner for job execution integration
with open(os.path.join(extract_dir,"src","queue","stub_runner.py"),"r") as f:
    print("".join(f.readlines()[:260]))

# Subsystem: Queue
# Role: Test stub for SingleNodeJobRunner - does not execute real jobs.

"""Test stub runner that satisfies SingleNodeJobRunner interface without execution.

PR-0114C-T(x): This module provides a StubRunner for tests that:
- Do not want to execute real SD/WebUI pipelines.
- Need to verify queue/controller wiring without side effects.
- Want to avoid threading issues in test environments.

Production code should never use StubRunner. It is strictly for test fixtures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.queue.job_model import Job
    from src.queue.job_queue import JobQueue

logger = logging.getLogger(__name__)


class StubRunner:
    """Test stub for SingleNodeJobRunner.

    - Satisfies the same interface as SingleNodeJobRunner.
    - Does not spawn a worker thread.
    - Does not call PipelineController._run_job or any SD/WebUI client.
    - Safe to use in controller/GUI tests that don't need real execution.
    """

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: object = None,
        poll_interval: float = 0.1,
        on_status_change: object = None,
    ) -> None:
        """Initialize StubRunner with same signature as SingleNodeJobRunner."""
        self._job_queue = job_queue
        self._run_callable = run_callable  # Ignored - we don't run jobs
        self._poll_interval = poll_interval
        self._on_status_change = on_status_change
        self._running = False
        self._current_job: Job | None = None

    def start(self) -> None:
        """Start the runner (no-op in stub)."""
        logger.debug("StubRunner.start() called - no actual execution")
        self._running = True

    def stop(self) -> None:
        """Stop the runner (no-op in stub)."""
        logger.debug("StubRunner.stop() called")
        self._running = False

    def is_running(self) -> bool:
        """Check if runner is 'running' (always returns current flag state)."""
        return self._running

    def run_once(self, job: Job) -> dict | None:
        """Synchronously 'run' a job (no-op, returns empty result)."""
        logger.debug("StubRunner.run_once() called for job %s - returning empty result", job.job_id)
        return {}

    def cancel_current(self) -> None:
        """Cancel current job (no-op in stub)."""
        logger.debug("StubRunner.cancel_current() called")
        self._current_job = None

    @property
    def current_job(self) -> Job | None:
        """Return current job (always None in stub)."""
        return self._current_job

Considering PR specifications and user’s plan
It seems we're not writing tests but specifying PRs. The user mentioned a previous DI PR with new tests, and the repository now includes a stub runner and DI. So, PR-A mainly addresses the run path without substantial changes. Given the user's request to generate PR-A & PR-B with the snapshot and analyze potential risks and high ROI, I'll adjust the final PR specs to reflect the current repo state and ensure minimal changes.

Defining PR specs and key objectives
The goal is to ensure the pipeline process works end-to-end with correct triggers for image generation and that panels (preview, queue, history) are functional. We must specify PRs step by step, not directly alter code. Given complexity, we’ll note known issues like failing tests or stray Python, but use stub runner DI in tests to address these in upcoming PRs.

Ensuring the pipeline works in production
For the pipeline to function in production, DI should be optional. The default SingleNodeJobRunner uses the real PipelineRunner with the proper run_callable. We confirmed that SingleNodeJobRunner handles job execution properly by using run_callable, which in turn processes the job through PipelineController. This ensures the pipeline runs correctly.

Clarifying PR-A scope
PR-A might not need code changes, focusing instead on documentation and tests to verify the run path. Small cleanups could include ensuring AppController builds JobService once and linking PipelineController to both JobService and JobHistoryService. Based on the user's request, PR-A might focus more on tests and orchestration, bridging pipeline_controller.run_pipeline vs _run_job.

Defining PR-A and its verification tasks
PR-A focuses on ensuring correct JobService wiring with DI and the RunnerProtocol. It verifies consistent use of pipeline_controller._run_job versus _execute_job. Well-targeted tests will check that the job queue functions correctly, using a stub runner to ensure the correct call chain. PR-B aligns the GUI with this pipeline path, refining event listeners and ensuring proper state changes in PipelineTabFrame.

Generating PR specs for pipeline run path
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "listen" in l.lower() and "job_draft" in l:
        print(i+1, l)

Searching for "job_draft" in pipeline view code
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "job_draft" in l:
        print(i+1, l)

233                 self.app_state.subscribe("job_draft", self._on_job_draft_changed)
241             self._on_job_draft_changed()
386     def _on_job_draft_changed(self) -> None:
390             job_draft = self.app_state.job_draft
392                 self.preview_panel.update_from_job_draft(job_draft)
Searching for "job_draft" in pipeline tab frame
print("\n".join(txt_pipe_tab.splitlines()[224:245]))

            except Exception:
                pass
        self._sync_state_overrides()
        self._handle_sidebar_change()

        if self.app_state is not None:
            try:
                self.app_state.add_resource_listener(self._on_app_state_resources_changed)
                self.app_state.subscribe("job_draft", self._on_job_draft_changed)
                self.app_state.subscribe("queue_items", self._on_queue_items_changed)
                self.app_state.subscribe("running_job", self._on_running_job_changed)
                self.app_state.subscribe("queue_status", self._on_queue_status_changed)
                self.app_state.subscribe("history_items", self._on_history_items_changed)
            except Exception:
                pass
            self._on_app_state_resources_changed(self.app_state.resources)
            self._on_job_draft_changed()
            self._on_queue_items_changed()
            self._on_running_job_changed()
            self._on_queue_status_changed()
            self._on_history_items_changed()
Crafting PR-A & PR-B specs and confirming dependencies
I'll begin by drafting PR-A and PR-B specs at a conceptual level, ensuring I reference the correct file paths. I’ll also check for potential issues, like the PipelineController using SDWebUIClient and PipelineRunner instead of the injected pipeline_runner. I need to confirm whether PipelineController accepts this parameter by reviewing its __init__.

Identifying pipeline controller initialization issues
for i,l in enumerate(txt_pc.splitlines()):
    if "def __init__" in l:
        print(i+1, l)
        print("\n".join(txt_pc.splitlines()[i:i+30]))
        break
487     def __init__(
    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        job_builder: JobBuilderV2 | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
Identifying potential issues in code and design
print("\n".join(txt_pc.splitlines()[517:575]))

        self._job_builder = job_builder if job_builder is not None else JobBuilderV2()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
                pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        history_service = self.get_job_history_service()
        self._job_service = (
            job_service
            if job_service is not None
            else JobService(queue, runner, history_store, history_service=history_service)
        )
        self._job_controller.set_status_callback("pipeline", self._on_job_status)

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_learning_runner_for_tests(self):
        """Return the learning runner instance for test inspection."""

        return self._get_learning_runner()

    def handle_learning_record(self, record: LearningRecord) -> None:
        """Handle learning records forwarded from pipeline runner."""

        self._last_learning_record = record
        if self._learning_record_writer and self._learning_enabled:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass

    def get_learning_record_handler(self):
        """Return a callback suitable for passing to PipelineRunner."""

        return self.handle_learning_record

Displaying truncated job service assignment data
print("\n".join(txt_pc.splitlines()[575:625]))

    def get_last_learning_record(self) -> LearningRecord | None:
        """Return the most recent LearningRecord handled by the controller."""

        return self._last_learning_record

    def set_learning_enabled(self, enabled: bool) -> None:
        """Enable or disable passive learning record emission."""

        self._learning_enabled = bool(enabled)

    def is_learning_enabled(self) -> bool:
        """Return whether learning record emission is enabled."""

        return self._learning_enabled

    def record_run_result(self, result: PipelineRunResult) -> None:
        """Record the last PipelineRunResult for inspection by higher layers/tests."""

        self._last_run_result = result
        self._last_stage_events = getattr(result, "stage_events", None)

    def get_last_run_result(self) -> PipelineRunResult | None:
        """Return the most recent PipelineRunResult recorded on this controller."""

        return self._last_run_result

    def validate_stage_plan(self, config: dict) -> StageExecutionPlan:
        """Build and store a stage execution plan for testing/inspection."""

        plan = build_stage_execution_plan(config)
        self._last_stage_execution_plan = plan
        return plan

    def get_last_stage_execution_plan_for_tests(self) -> StageExecutionPlan | None:
        """Return the most recent StageExecutionPlan built by this controller."""

        return self._last_stage_execution_plan

    def get_last_run_config_for_tests(self) -> dict[str, Any] | None:
        return self._last_run_config

    def get_last_stage_events_for_tests(self) -> list[dict] | None:
        """Return last emitted stage events."""

        return self._last_stage_events

    # Queue-backed execution -------------------------------------------------
    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
Searching for lost _job_service assignment
for i,l in enumerate(txt_pc.splitlines()):
    if "self._job_service = (" in l:
        print(i+1, l)
        print("\n".join(txt_pc.splitlines()[i-4:i+4]))

533         self._job_service = (
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        history_service = self.get_job_history_service()
        self._job_service = (
            job_service
            if job_service is not None
            else JobService(queue, runner, history_store, history_service=history_service)
Inspecting JobExecutionController for run path details
Alright, I need to check where PipelineController uses JobExecutionController and queue_execution_controller to understand the run path better. I’ll have to inspect the JobExecutionController to get a clearer picture of how everything is connected. That should help me map out the full workflow.

Inspecting job_execution_controller path location
for root,dirs,files in os.walk(os.path.join(extract_dir,"src")):
    for fn in files:
        if fn=="job_execution_controller.py":
            print(os.path.join(root,fn))

/mnt/data/repo/src/controller/job_execution_controller.py
Inspecting JobExecutionController source code
with open(os.path.join(extract_dir,"src","controller","job_execution_controller.py"),"r") as f:
    print("".join(f.readlines()[:260]))

"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore, JSONLJobHistoryStore
from pathlib import Path
from src.config.app_config import get_job_history_path
from src.cluster.worker_registry import WorkerRegistry
from src.cluster.worker_model import WorkerDescriptor


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._runner = SingleNodeJobRunner(
            self._queue, self._execute_job, poll_interval=poll_interval, on_status_change=self._on_status
        )
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._runner.start()
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._started:
                self._runner.stop()
                self._started = False

    def submit_pipeline_run(self, pipeline_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(job_id=job_id, pipeline_config=None, priority=priority, payload=pipeline_callable, worker_id=worker_id)
        self._queue.submit(job)
        self.start()
        return job_id

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will skip it if not already running.
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if job and job.status == JobStatus.QUEUED:
            job.mark_status(JobStatus.CANCELLED)

    def get_job_status(self, job_id: str) -> JobStatus | None:
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        return job.status if job else None

    def set_status_callback(self, key: str, callback: Callable[[Job, JobStatus], None]) -> None:
        self._callbacks[key] = callback

    def clear_status_callback(self, key: str) -> None:
        self._callbacks.pop(key, None)

    def _on_status(self, job: Job, status: JobStatus) -> None:
        for cb in list(self._callbacks.values()):
            try:
                cb(job, status)
            except Exception:
                pass

    def get_history_store(self) -> JobHistoryStore:
        return self._history_store

    def get_queue(self) -> JobQueue:
        return self._queue

    def get_worker_registry(self) -> WorkerRegistry:
        return self._worker_registry

    def get_runner(self) -> SingleNodeJobRunner:
        return self._runner

    def _default_history_store(self) -> JobHistoryStore:
        path = Path(get_job_history_path())
        return JSONLJobHistoryStore(path)

Clarifying DI and job path in PR-A and PR-B
For PR-A, the goal seems to be clarifying DI between JobExecutionController, JobService, PipelineController, and AppController. We won't modify JobExecutionController since it’s part of the cluster subsystem. Both PR-A and PR-B should remain moderate but critical. PR-A focuses on adding job service paths with proper DI, particularly in app_factory.py. I'll need to inspect this file to see how we can implement that.

Clarifying dependency injection in pipeline controllers
with open(os.path.join(extract_dir,"src","app_factory.py"),"r") as f:
    print("".join(f.readlines()[:260]))

from __future__ import annotations

import tkinter as tk
from typing import Optional, Tuple

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.api.webui_process_manager import WebUIProcessManager
from src.utils.config import ConfigManager
from src.utils import attach_gui_log_handler


def build_v2_app(
    *,
    root: Optional[tk.Tk] = None,
    pipeline_runner=None,
    webui_manager: WebUIProcessManager | None = None,
    threaded: bool = False,
    config_manager: ConfigManager | None = None,
) -> Tuple[tk.Tk, AppStateV2, AppController, MainWindowV2]:
    """
    Build the V2 application stack with injectable runner for tests.

    Returns (root, app_state, app_controller, window).
    """

    if root is None:
        root = tk.Tk()

    app_state = AppStateV2()

    # Create controller first to get gui_log_handler
    config_manager = config_manager or ConfigManager()
    app_controller = AppController(
        None,  # main_window=None for now
        pipeline_runner=pipeline_runner,
        threaded=threaded,
        webui_process_manager=webui_manager,
        config_manager=config_manager,
    )

    window = MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=None,
        pipeline_controller=app_controller.pipeline_controller,
        gui_log_handler=app_controller.get_gui_log_handler(),
    )

    # Now set the main_window on controller
    app_controller.set_main_window(window)

    return root, app_state, app_controller, window

Finalizing PR specifications
Based on the user’s priorities, we'll focus on clear PR specs that describe the existing DI and run path, while adding tests and minor adjustments where needed. A key improvement is in PipelineController._run_job, where we could prioritize using _pipeline_runner consistently. We’ll also look into potential issues with SingleNodeJobRunner.run_once and JobService.run_now.

Creating PRs with updates and minor adjustments
with open(os.path.join(extract_dir,"src","controller","job_service.py"),"r") as f:
    print("".join(f.readlines()[120:260]))


    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
            self._record_job_history(job, status)
        elif status in {JobStatus.CANCELLED, JobStatus.FAILED}:
            self._emit(self.EVENT_JOB_FAILED, job)
            if status == JobStatus.FAILED:
                self._record_job_history(job, status)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _record_job_history(self, job: Job, status: JobStatus) -> None:
        if not self._history_service:
            return
        try:
            if status == JobStatus.COMPLETED:
                self._history_service.record(job, result=job.result)
            elif status == JobStatus.FAILED:
                self._history_service.record_failure(job, error=job.error_message)
        except Exception:
            logging.debug("Failed to record job history for %s", job.job_id, exc_info=True)

    def _emit_queue_updated(self) -> None:
        jobs = self.job_queue.list_jobs()
        summaries = [format_queue_job_summary(job) for job in jobs]
        self._emit(self.EVENT_QUEUE_UPDATED, summaries)

    def _set_queue_status(self, status: QueueStatus) -> None:
        if self._queue_status != status:
            self._queue_status = status
            self._emit(self.EVENT_QUEUE_STATUS, status)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            try:
                callback(*args)
            except Exception:
                continue

Displaying job_service.py code for comparison
with open(os.path.join(extract_dir,"src","controller","job_service.py"),"r") as f:
    print("".join(f.readlines()[260:420]))


Displaying file content with line numbers
with open(os.path.join(extract_dir,"src","controller","job_service.py"),"r") as f:
    js_lines = f.read().splitlines()
for i,l in enumerate(js_lines):
    print(f"{i+1:3}: {l}")

  1: """JobService bridges JobQueue, runner, and history for higher-level orchestration."""
  2: 
  3: from __future__ import annotations
  4: 
  5: import logging
  6: 
  7: from typing import Any, Callable, Literal, Protocol
  8: 
  9: from src.controller.job_history_service import JobHistoryService
 10: from src.queue.job_model import Job, JobStatus
 11: from src.gui.pipeline_panel_v2 import format_queue_job_summary
 12: from src.queue.job_queue import JobQueue
 13: from src.queue.single_node_runner import SingleNodeJobRunner
 14: from src.queue.job_history_store import JobHistoryStore
 15: 
 16: QueueStatus = Literal["idle", "running", "paused"]
 17: 
 18: 
 19: class RunnerProtocol(Protocol):
 20:     """Protocol for job runners (SingleNodeJobRunner, StubRunner, etc.)."""
 21: 
 22:     def start(self) -> None: ...
 23:     def stop(self) -> None: ...
 24:     def is_running(self) -> bool: ...
 25:     def run_once(self, job: Job) -> dict | None: ...
 26:     def cancel_current(self) -> None: ...
 27: 
 28: 
 29: # Type alias for runner factory callable
 30: RunnerFactory = Callable[[JobQueue, Callable[[Job], dict] | None], RunnerProtocol]
 31: 
 32: 
 33: class JobService:
 34:     """Bridge between JobQueue, runner, and history for higher-level orchestration.
 35: 
 36:     PR-0114C-T(x): Supports dependency injection for runner and history service:
 37:     - runner: Direct runner instance (legacy API, for backward compat)
 38:     - runner_factory: Factory callable to create runner (preferred for DI)
 39:     - history_service: History service instance (can be NullHistoryService in tests)
 40:     """
 41: 
 42:     EVENT_QUEUE_UPDATED = "queue_updated"
 43:     EVENT_JOB_STARTED = "job_started"
 44:     EVENT_JOB_FINISHED = "job_finished"
 45:     EVENT_JOB_FAILED = "job_failed"
 46:     EVENT_QUEUE_EMPTY = "queue_empty"
 47:     EVENT_QUEUE_STATUS = "queue_status"
 48: 
 49:     def __init__(
 50:         self,
 51:         job_queue: JobQueue,
 52:         runner: RunnerProtocol | None = None,
 53:         history_store: JobHistoryStore | None = None,
 54:         history_service: JobHistoryService | None = None,
 55:         *,
 56:         runner_factory: RunnerFactory | None = None,
 57:         run_callable: Callable[[Job], dict] | None = None,
 58:     ) -> None:
 59:         """Initialize JobService with queue, runner, and history dependencies.
 60: 
 61:         Args:
 62:             job_queue: The job queue to manage.
 63:             runner: Direct runner instance (legacy API). If None, uses runner_factory.
 64:             history_store: Optional history store for persistence.
 65:             history_service: Optional history service. If None and history_store
 66:                 provided, creates a default JobHistoryService.
 67:             runner_factory: Factory to create runner. Signature:
 68:                 (job_queue, run_callable) -> RunnerProtocol.
 69:                 If both runner and runner_factory are None, creates SingleNodeJobRunner.
 70:             run_callable: Callable to execute jobs, passed to runner/factory.
 71:         """
 72:         self.job_queue = job_queue
 73:         self.history_store = history_store
 74:         self._run_callable = run_callable
 75: 
 76:         # PR-0114C-T(x): Support runner injection via factory or direct instance
 77:         if runner is not None:
 78:             self.runner = runner
 79:         elif runner_factory is not None:
 80:             self.runner = runner_factory(job_queue, run_callable)
 81:         else:
 82:             # Default: create SingleNodeJobRunner (production behavior)
 83:             self.runner = SingleNodeJobRunner(
 84:                 job_queue,
 85:                 run_callable=run_callable,
 86:                 poll_interval=0.05,
 87:             )
 88: 
 89:         # PR-0114C-T(x): Support history service injection
 90:         self._history_service = history_service
 91:         if self._history_service is None and history_store is not None:
 92:             try:
 93:                 self._history_service = JobHistoryService(job_queue, history_store)
 94:             except Exception:
 95:                 self._history_service = None
 96: 
 97:         self._listeners: dict[str, list[Callable[..., None]]] = {}
 98:         self._queue_status: QueueStatus = "idle"
 99:         self.job_queue.register_status_callback(self._handle_job_status_change)
100: 
101:     @property
102:     def queue(self) -> JobQueue:
103:         """Alias for job_queue for controller compatibility."""
104:         return self.job_queue
105: 
106:     def register_callback(self, event: str, callback: Callable[..., None]) -> None:
107:         self._listeners.setdefault(event, []).append(callback)
108: 
109:     def enqueue(self, job: Job) -> None:
110:         self.job_queue.submit(job)
111:         self._emit_queue_updated()
112: 
113:     def run_now(self, job: Job) -> None:
114:         self.enqueue(job)
115:         try:
116:             self.run_next_now()
117:         except Exception:
118:             pass
119:         if not self.runner.is_running():
120:             self.runner.start()
121: 
122:     def submit_job_with_run_mode(self, job: Job) -> None:
123:         """Submit a job respecting its configured run_mode."""
124:         mode = (job.run_mode or "queue").lower()
125:         logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
126:         if mode == "direct":
127:             self.submit_direct(job)
128:         else:
129:             self.submit_queued(job)
130: 
131:     def submit_direct(self, job: Job) -> dict | None:
132:         """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
133:         
134:         PR-106: Explicit API for direct execution path.
135:         """
136:         logging.info("Direct execution of job %s", job.job_id)
137:         self.job_queue.submit(job)
138:         self._emit_queue_updated()
139:         try:
140:             result = self.runner.run_once(job)
141:             return result
142:         except Exception:
143:             raise
144: 
145:     def submit_queued(self, job: Job) -> None:
146:         """Submit a job to the queue for background execution.
147:         
148:         PR-106: Explicit API for queued execution path.
149:         """
150:         logging.info("Queuing job %s for background execution", job.job_id)
151:         self.enqueue(job)
152:         if not self.runner.is_running():
153:             self.runner.start()
154: 
155:     def submit_jobs(self, jobs: list[Job]) -> None:
156:         """Submit multiple jobs respecting each job's configured run_mode.
157:         
158:         PR-044: Batch submission for randomizer variant jobs.
159:         """
160:         for job in jobs:
161:             self.submit_job_with_run_mode(job)
162: 
163:     def pause(self) -> None:
164:         self.runner.stop()
165:         self._set_queue_status("paused")
166: 
167:     def resume(self) -> None:
168:         self.runner.start()
169:         self._set_queue_status("running")
170: 
171:     def cancel_current(self) -> None:
172:         current = getattr(self.runner, "current_job", None)
173:         if current:
174:             self.job_queue.mark_cancelled(current.job_id)
175:         self.runner.cancel_current()
176:         self._set_queue_status("idle")
177: 
178:     def list_queue(self) -> list[Job]:
179:         return self.job_queue.list_jobs()
180: 
181:     def run_next_now(self) -> None:
182:         """Synchronously run the next queued job via the runner."""
183:         job = self.job_queue.get_next_job()
184:         if job is None:
185:             return
186:         self._set_queue_status("running")
187:         try:
188:             self.runner.run_once(job)
189:         finally:
190:             if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
191:                 self._set_queue_status("idle")
192: 
193:     def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
194:         if status == JobStatus.RUNNING:
195:             self._emit(self.EVENT_JOB_STARTED, job)
196:         elif status == JobStatus.COMPLETED:
197:             self._emit(self.EVENT_JOB_FINISHED, job)
198:             self._record_job_history(job, status)
199:         elif status in {JobStatus.CANCELLED, JobStatus.FAILED}:
200:             self._emit(self.EVENT_JOB_FAILED, job)
201:             if status == JobStatus.FAILED:
202:                 self._record_job_history(job, status)
203:         self._emit_queue_updated()
204:         if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
205:             self._emit(self.EVENT_QUEUE_EMPTY)
206: 
207:     def _record_job_history(self, job: Job, status: JobStatus) -> None:
208:         if not self._history_service:
209:             return
210:         try:
211:             if status == JobStatus.COMPLETED:
212:                 self._history_service.record(job, result=job.result)
213:             elif status == JobStatus.FAILED:
214:                 self._history_service.record_failure(job, error=job.error_message)
215:         except Exception:
216:             logging.debug("Failed to record job history for %s", job.job_id, exc_info=True)
217: 
218:     def _emit_queue_updated(self) -> None:
219:         jobs = self.job_queue.list_jobs()
220:         summaries = [format_queue_job_summary(job) for job in jobs]
221:         self._emit(self.EVENT_QUEUE_UPDATED, summaries)
222: 
223:     def _set_queue_status(self, status: QueueStatus) -> None:
224:         if self._queue_status != status:
225:             self._queue_status = status
226:             self._emit(self.EVENT_QUEUE_STATUS, status)
227: 
228:     def _emit(self, event: str, *args: Any) -> None:
229:         for callback in self._listeners.get(event, []):
230:             try:
231:                 callback(*args)
232:             except Exception:
233:                 continue
Extracting mid section lines 40 to 180
print("\n".join(js_lines[40:190]))


    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: RunnerProtocol | None = None,
        history_store: JobHistoryStore | None = None,
        history_service: JobHistoryService | None = None,
        *,
        runner_factory: RunnerFactory | None = None,
        run_callable: Callable[[Job], dict] | None = None,
    ) -> None:
        """Initialize JobService with queue, runner, and history dependencies.

        Args:
            job_queue: The job queue to manage.
            runner: Direct runner instance (legacy API). If None, uses runner_factory.
            history_store: Optional history store for persistence.
            history_service: Optional history service. If None and history_store
                provided, creates a default JobHistoryService.
            runner_factory: Factory to create runner. Signature:
                (job_queue, run_callable) -> RunnerProtocol.
                If both runner and runner_factory are None, creates SingleNodeJobRunner.
            run_callable: Callable to execute jobs, passed to runner/factory.
        """
        self.job_queue = job_queue
        self.history_store = history_store
        self._run_callable = run_callable

        # PR-0114C-T(x): Support runner injection via factory or direct instance
        if runner is not None:
            self.runner = runner
        elif runner_factory is not None:
            self.runner = runner_factory(job_queue, run_callable)
        else:
            # Default: create SingleNodeJobRunner (production behavior)
            self.runner = SingleNodeJobRunner(
                job_queue,
                run_callable=run_callable,
                poll_interval=0.05,
            )

        # PR-0114C-T(x): Support history service injection
        self._history_service = history_service
        if self._history_service is None and history_store is not None:
            try:
                self._history_service = JobHistoryService(job_queue, history_store)
            except Exception:
                self._history_service = None

        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.job_queue.register_status_callback(self._handle_job_status_change)

    @property
    def queue(self) -> JobQueue:
        """Alias for job_queue for controller compatibility."""
        return self.job_queue

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
Extracting mid section lines 40-180
print("\n".join(js_lines[80:160]))

        else:
            # Default: create SingleNodeJobRunner (production behavior)
            self.runner = SingleNodeJobRunner(
                job_queue,
                run_callable=run_callable,
                poll_interval=0.05,
            )

        # PR-0114C-T(x): Support history service injection
        self._history_service = history_service
        if self._history_service is None and history_store is not None:
            try:
                self._history_service = JobHistoryService(job_queue, history_store)
            except Exception:
                self._history_service = None

        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.job_queue.register_status_callback(self._handle_job_status_change)

    @property
    def queue(self) -> JobQueue:
        """Alias for job_queue for controller compatibility."""
        return self.job_queue

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
Displaying selected lines from code
print("\n".join(js_lines[120:210]))


    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
            self._record_job_history(job, status)
        elif status in {JobStatus.CANCELLED, JobStatus.FAILED}:
            self._emit(self.EVENT_JOB_FAILED, job)
            if status == JobStatus.FAILED:
                self._record_job_history(job, status)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _record_job_history(self, job: Job, status: JobStatus) -> None:
        if not self._history_service:
            return
        try:
Inspecting submit_direct function body
print("\n".join(js_lines[130:170]))

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

Generating PRs for core run path and runner DI
for i,l in enumerate(txt_pc.splitlines()):
    if "def _execute_job" in l:
        print(i+1, l)

749     def _execute_job(self, job: Any) -> dict[Any, Any]:
Evaluating core run path and runner dependency injection
print("\n".join(txt_pc.splitlines()[744:790]))

                pass
            return True
        return False

    def _execute_job(self, job: Any) -> dict[Any, Any]:
        if hasattr(job, "payload") and callable(job.payload):
            result = job.payload()
            if isinstance(result, dict):
                return result
            return {}
        return {}

    def _on_job_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(job.job_id, status)

    def _on_queue_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(getattr(job, "job_id", None), status)

    def _handle_status(self, job_id: str | None, status: JobStatus) -> None:
        if job_id is None or job_id != self._active_job_id:
            return
        if status == JobStatus.COMPLETED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.FAILED:
            try:
                self.state_manager.transition_to(GUIState.ERROR)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.CANCELLED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass

    def submit_run_plan(
Assessing duplication between AppController and PipelineController
for i,l in enumerate(txt_pc.splitlines()[260:360]):
    print(f"{i+1+260:3}: {l}")

261:             jobs = self._job_builder.build_jobs(
262:                 base_config=base_config,
263:                 randomization_plan=randomization_plan,
264:                 batch_settings=batch_settings,
265:                 output_settings=output_settings,
266:             )
267:         except Exception as exc:
268:             _logger.warning("JobBuilderV2 failed to build jobs: %s", exc)
269:             return []
270: 
271:         if not jobs:
272:             _logger.warning("JobBuilderV2 returned no jobs for current state")
273: 
274:         return jobs
275: 
276:     def get_preview_jobs(self) -> list[NormalizedJobRecord]:
277:         """Return normalized jobs derived from the current GUI state for preview panels."""
278:         try:
279:             return self._build_normalized_jobs_from_state()
280:         except Exception as exc:
281:             _logger.debug("Failed to build preview jobs: %s", exc)
282:             return []
283: 
284:     def _to_queue_job(
285:         self,
286:         record: NormalizedJobRecord,
287:         *,
288:         run_mode: str = "queue",
289:         source: str = "gui",
290:         prompt_source: str = "manual",
291:         prompt_pack_id: str | None = None,
292:     ) -> Job:
293:         """Convert a NormalizedJobRecord into the Job model used by JobService.
294: 
295:         This adapter preserves all metadata from the normalized record
296:         while producing a Job compatible with the existing queue system.
297:         """
298:         # Get config snapshot from normalized record
299:         config_snapshot = record.to_queue_snapshot()
300: 
301:         # Extract pipeline_config from record.config if it's the right type
302:         pipeline_config = None
303:         if isinstance(record.config, PipelineConfig):
304:             pipeline_config = record.config
305:         elif hasattr(record.config, "__dict__"):
306:             # Try to construct PipelineConfig from dict-like object
307:             try:
308:                 pipeline_config = record.config
309:             except Exception:
310:                 pass
311: 
312:         # Build randomizer metadata from record
313:         randomizer_metadata = record.randomizer_summary
314: 
315:         return Job(
316:             job_id=record.job_id,
317:             pipeline_config=pipeline_config,
318:             priority=JobPriority.NORMAL,
319:             run_mode=run_mode,
320:             source=source,
321:             prompt_source=prompt_source,
322:             prompt_pack_id=prompt_pack_id,
323:             config_snapshot=config_snapshot,
324:             randomizer_metadata=randomizer_metadata,
325:             variant_index=record.variant_index,
326:             variant_total=record.variant_total,
327:             learning_enabled=self._learning_enabled,
328:         )
329: 
330:     def start_pipeline_v2(
331:         self,
332:         *,
333:         run_mode: str | None = None,
334:         source: str = "gui",
335:         prompt_source: str = "manual",
336:         prompt_pack_id: str | None = None,
337:         on_complete: Callable[[dict[Any, Any]], None] | None = None,
338:         on_error: Callable[[Exception], None] | None = None,
339:     ) -> bool:
340:         """Start pipeline using V2 job building via JobBuilderV2.
341: 
342:         This is the new V2 run entrypoint that:
343:         1. Builds normalized jobs via JobBuilderV2
344:         2. Converts them to queue Jobs
345:         3. Submits via JobService respecting run_mode
346: 
347:         Args:
348:             run_mode: Force "direct" or "queue". If None, uses state.
349:             source: Job source for provenance (e.g., "gui", "api").
350:             prompt_source: Prompt source type (e.g., "manual", "pack").
351:             prompt_pack_id: Optional prompt pack ID if using packs.
352:             on_complete: Callback on successful completion.
353:             on_error: Callback on error.
354: 
355:         Returns:
356:             True if jobs were submitted, False otherwise.
357:         """
358:         if not self.state_manager.can_run():
359:             return False
360: 
Displaying specific text lines from document
print("\n".join(txt_pc.splitlines()[360:430]))

        # Check WebUI connection
        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        # Resolve run mode
        if run_mode is None:
            try:
                pipeline_state = getattr(self.state_manager, "pipeline_state", None)
                if pipeline_state:
                    run_mode = self._normalize_run_mode(pipeline_state)
                else:
                    run_mode = "queue"
            except Exception:
                run_mode = "queue"

        # Build normalized jobs
        try:
            normalized_jobs = self._build_normalized_jobs_from_state()
        except Exception as exc:
            _logger.error("Failed to build normalized jobs: %s", exc)
            if on_error:
                on_error(exc)
            return False

        if not normalized_jobs:
            _logger.warning("No jobs to submit")
            return False

        # Convert and submit each job
        submitted_count = 0
        for record in normalized_jobs:
            try:
                job = self._to_queue_job(
                    record,
                    run_mode=run_mode,
                    source=source,
                    prompt_source=prompt_source,
                    prompt_pack_id=prompt_pack_id,
                )
                # Attach payload for execution
                job.payload = lambda j=job: self._run_job(j)

                self._job_service.submit_job_with_run_mode(job)
                submitted_count += 1
            except Exception as exc:
                _logger.error("Failed to submit job %s: %s", record.job_id, exc)
                if on_error:
                    on_error(exc)

        if submitted_count > 0:
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass
            _logger.info("Submitted %d jobs via V2 pipeline", submitted_count)
            return True

        return False

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
Displaying text from specific line range
print("\n".join(txt_pc.splitlines()[430:480]))

    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path
        from src.learning.model_profiles import find_model_profile_for_checkpoint, find_lora_profile_for_name, suggest_preset_for
        # Resolve checkpoint path (stub: assumes models are in 'models/' dir)
        checkpoint_path = Path("models") / f"{base_model_name}.ckpt"
        model_profile = find_model_profile_for_checkpoint(checkpoint_path)
        lora_search_paths = [Path("loras")]
        lora_profiles = [find_lora_profile_for_name(name, lora_search_paths) for name in lora_names]
        lora_profiles = [lp for lp in lora_profiles if lp]
        suggested = suggest_preset_for(model_profile, lora_profiles)
        # Start from default config
        config = self.get_default_config() if hasattr(self, "get_default_config") else {}
        # Always ensure txt2img key exists and populate with defaults if missing
        if "txt2img" not in config:
            config["txt2img"] = {
                "sampler_name": "Euler",
                "scheduler": None,
                "steps": 20,
                "cfg_scale": 5.0,
                "width": 512,
                "height": 512,
                "loras": [],
            }
        # Apply suggested preset if available
        if suggested:
            config["txt2img"].update({
                "sampler_name": suggested.sampler,
                "scheduler": suggested.scheduler,
                "steps": suggested.steps,
                "cfg_scale": suggested.cfg,
                "width": suggested.resolution[0],
                "height": suggested.resolution[1],
            })
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)} for name in lora_names
            ]
            import logging
            logging.info(f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}.")
        # Apply user overrides last
        for k, v in user_overrides.items():
            # Map common override keys to txt2img
            if k in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "loras"):
                config["txt2img"][k] = v
            elif k == "cfg":
                config["txt2img"]["cfg_scale"] = v
            elif k == "resolution" and isinstance(v, (tuple, list)) and len(v) == 2:
                config["txt2img"]["width"] = v[0]
                config["txt2img"]["height"] = v[1]
Searching for 'start_pipeline_v2' function location
for i,l in enumerate(txt_pc.splitlines()):
    if "start_pipeline_v2" in l:
        print(i+1, l)
        print("\n".join(txt_pc.splitlines()[i:i+40]))

330     def start_pipeline_v2(
    def start_pipeline_v2(
        self,
        *,
        run_mode: str | None = None,
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Start pipeline using V2 job building via JobBuilderV2.

        This is the new V2 run entrypoint that:
        1. Builds normalized jobs via JobBuilderV2
        2. Converts them to queue Jobs
        3. Submits via JobService respecting run_mode

        Args:
            run_mode: Force "direct" or "queue". If None, uses state.
            source: Job source for provenance (e.g., "gui", "api").
            prompt_source: Prompt source type (e.g., "manual", "pack").
            prompt_pack_id: Optional prompt pack ID if using packs.
            on_complete: Callback on successful completion.
            on_error: Callback on error.

        Returns:
            True if jobs were submitted, False otherwise.
        """
        if not self.state_manager.can_run():
            return False

        # Check WebUI connection
        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False
Inspecting PipelineTabFrame constructors
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "class PipelineTabFrameV2" in l:
        print(i+1, l)
        print("\n".join(txt_pipe_tab.splitlines()[i:i+40]))
        break
Viewing file contents (first 120 lines)
print("\n".join(txt_pipe_tab.splitlines()[:120]))

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as design_system
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.state import PipelineState
from src.gui.theme_v2 import CARD_FRAME_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.views.stage_cards_panel import StageCardsPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.zone_map_v2 import get_pipeline_stage_order
from src.pipeline.job_models_v2 import NormalizedJobRecord


class PipelineTabFrame(ttk.Frame):
    """Layout scaffold for the Pipeline tab."""

    DEFAULT_COLUMN_WIDTH = design_system.Spacing.XL * 40  # ~640
    MIN_COLUMN_WIDTH = design_system.Spacing.XL * 25  # ~400
    LOGGING_ROW_MIN_HEIGHT = design_system.Spacing.XL * 10
    LOGGING_ROW_WEIGHT = 1

    def __init__(
        self,
        master: tk.Misc,
        *,
        prompt_workspace_state: Any = None,
        app_state: Any = None,
        app_controller: Any = None,
        pipeline_controller: Any = None,
        theme: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.app_controller = app_controller
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        # Initialize pipeline state and enable variables for test compatibility
        self.pipeline_state = PipelineState()

        self.rowconfigure(0, weight=1)
        for idx in range(3):
            self.columnconfigure(idx, weight=1, minsize=self.DEFAULT_COLUMN_WIDTH)

        def _create_card(parent: ttk.Frame) -> ttk.Frame:
            card = ttk.Frame(parent, padding=12, style=CARD_FRAME_STYLE)
            card.columnconfigure(0, weight=1)
            return card

        self.left_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.left_column.grid(row=0, column=0, sticky="nsew")
        self.left_column.rowconfigure(0, weight=1)
        self.left_column.columnconfigure(0, weight=1)
        self.left_scroll = ScrollableFrame(self.left_column, style=CARD_FRAME_STYLE)
        self.left_scroll.grid(row=0, column=0, sticky="nsew")
        self.left_inner = self.left_scroll.inner

        # PR-GUI-H: Remove redundant sidebar_card wrapper - SidebarPanelV2 directly in scroll inner
        self.sidebar = SidebarPanelV2(
            self.left_inner,
            controller=self.app_controller or self.pipeline_controller,
            app_state=self.app_state,
            theme=self.theme,
            on_change=lambda: self._handle_sidebar_change(),
        )
        self.sidebar.pack(fill="both", pady=(0, 12), expand=True)

        # PR-GUI-H: prompt_text and restore_last_run_button moved to sidebar Pack Selector card
        # Keep references for compatibility
        self.prompt_text = getattr(self.sidebar, "prompt_text", tk.Entry(self.left_inner))
        self.restore_last_run_button = getattr(self.sidebar, "restore_last_run_button", None)
        if self.prompt_text:
            attach_tooltip(self.prompt_text, "Primary text prompt for the active pipeline.")
        # JT05-friendly attribute for tracking the img2img/upscale input image path
        self.input_image_path: str = ""

        self.center_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.center_column.grid(row=0, column=1, sticky="nsew")
        self.center_column.rowconfigure(0, weight=1)
        self.center_column.columnconfigure(0, weight=1)
        self.stage_scroll = ScrollableFrame(self.center_column, style=CARD_FRAME_STYLE)
        self.stage_scroll.grid(row=0, column=0, sticky="nsew")
        self.stage_cards_frame = self.stage_scroll.inner

        self.right_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.right_column.grid(row=0, column=2, sticky="nsew")
        self.right_column.rowconfigure(0, weight=1)
        self.right_column.columnconfigure(0, weight=1)
        queue_controller = self.app_controller or self.pipeline_controller

        self.right_scroll = ScrollableFrame(self.right_column, style=CARD_FRAME_STYLE)
        self.right_scroll.grid(row=0, column=0, sticky="nsew")
        self.right_scroll.inner.columnconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(3, weight=1)  # History row gets weight

        preview_card = _create_card(self.right_scroll.inner)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 8))
        preview_card.rowconfigure(0, weight=1)
        self.preview_panel = PreviewPanelV2(
            preview_card,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.preview_panel.grid(row=0, column=0, sticky="nsew")

        # PR-GUI-F1: Run Controls panel removed - controls moved to QueuePanelV2

Finding __init__ method in pipeline tab
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "def __init__" in l:
        print(i+1, l)
        print("\n".join(txt_pipe_tab.splitlines()[i:i+40]))
        break
30     def __init__(
    def __init__(
        self,
        master: tk.Misc,
        *,
        prompt_workspace_state: Any = None,
        app_state: Any = None,
        app_controller: Any = None,
        pipeline_controller: Any = None,
        theme: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.app_controller = app_controller
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        # Initialize pipeline state and enable variables for test compatibility
        self.pipeline_state = PipelineState()

        self.rowconfigure(0, weight=1)
        for idx in range(3):
            self.columnconfigure(idx, weight=1, minsize=self.DEFAULT_COLUMN_WIDTH)

        def _create_card(parent: ttk.Frame) -> ttk.Frame:
            card = ttk.Frame(parent, padding=12, style=CARD_FRAME_STYLE)
            card.columnconfigure(0, weight=1)
            return card

        self.left_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.left_column.grid(row=0, column=0, sticky="nsew")
        self.left_column.rowconfigure(0, weight=1)
        self.left_column.columnconfigure(0, weight=1)
        self.left_scroll = ScrollableFrame(self.left_column, style=CARD_FRAME_STYLE)
        self.left_scroll.grid(row=0, column=0, sticky="nsew")
        self.left_inner = self.left_scroll.inner

        # PR-GUI-H: Remove redundant sidebar_card wrapper - SidebarPanelV2 directly in scroll inner
Searching for queue controller assignments
for i,l in enumerate(txt_pipe_tab.splitlines()):
    if "queue_controller" in l:
        print(i+1, l)

100         queue_controller = self.app_controller or self.pipeline_controller
113             controller=queue_controller,
125             controller=queue_controller,
134             controller=queue_controller,
144             controller=queue_controller,
Thought for 12m 43s