PR-106 – RunMode Enforcement in PipelineController.md

PR-ID: PR-106
Risk: Medium (Tier 2 – controller + queue integration)
Goal: Make run_mode actually drive how runs flow through the system:

run_mode == "direct" → synchronous “fire once” execution (no queue scheduling), but still recorded in history.

run_mode == "queue" → enqueued and executed by SingleNodeJobRunner via the normal queue path.

This PR does not change GUI wiring or Learning; it’s purely about how PipelineController + JobService + runner use run_mode.

Preconditions / Assumptions

From earlier PRs (090–101 / 097–099):

Job (or equivalent) already has a run_mode field ("direct" vs "queue").

PipelineController builds jobs with run_mode based on PipelineState.run_mode.

GUI entrypoints call:

AppController.start_run_v2() → defaults run_mode to "direct" when unset.

AppController.on_run_job_now_v2() → defaults run_mode to "queue" when unset.

Job history already persists run_mode.

We will build on that instead of re-deriving it.

Scope
In-Scope Files

Adjust names to actual paths; these are conceptual targets:

src/controller/pipeline_controller.py

src/queue/job_model.py (or src/pipeline/job_model.py – wherever Job is defined)

src/queue/job_service.py (or job_execution_controller.py if that’s your facade)

src/queue/single_node_job_runner.py

Tests (new/updated)

tests/pipeline/test_run_modes.py (new – end-to-end-ish behavior for direct vs queue)

Optionally small unit tests:

tests/queue/test_job_service_run_modes.py

tests/controller/test_pipeline_controller_run_modes.py

Out-of-Scope

No changes to:

src/main.py

src/pipeline/executor.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

No GUI wiring or layout changes.

No Learning tab or LearningRecord wiring.

No changes to WebUI calls.

Desired Behavior
1. Direct vs Queue semantics

Direct:

run_mode == "direct".

Job is not scheduled via the normal FIFO queue.

Instead, PipelineController asks JobService to run synchronously:

Wait until SingleNodeJobRunner finishes.

Job is still recorded in JobHistoryStore with:

run_mode="direct",

a source like "run" / "manual".

This is the “press Run, do it now, don’t sit in the queue” behavior.

Queue:

run_mode == "queue".

Job is enqueued via JobService.

SingleNodeJobRunner later picks it up and executes it.

Job is recorded in history with run_mode="queue" and appropriate source (e.g. "run_now" or "add_to_queue").

2. Required metadata per job

Ensure every job has:

run_mode – already present.

source – e.g. "run", "run_now", "add_to_queue", "system".

prompt_source – e.g. "manual" vs "pack" (or "pack:<id>").

config_snapshot – either:

config_snapshot_id, if you use an external snapshot store, or

config_snapshot inline (full or trimmed PipelineConfig).

We do not redesign your whole schema; we just extend what’s already there to make it explicit and consistent.

Step-by-Step Implementation
Step 1 – Extend Job model with source + prompt/config metadata

File: src/queue/job_model.py (or analogous)

If you have something like:

@dataclass
class Job:
    job_id: str
    created_at: datetime
    config: PipelineConfig
    run_mode: str = "queue"
    ...


Extend it with:

@dataclass
class Job:
    job_id: str
    created_at: datetime
    config: PipelineConfig

    # Existing:
    run_mode: str = "queue"

    # NEW:
    source: str = "unknown"  # "run", "run_now", "add_to_queue", "system", etc.
    prompt_source: str = "manual"  # "manual" or "pack"
    prompt_pack_id: str | None = None  # when derived from a pack, else None

    # Optional – pick one pattern:
    config_snapshot_id: str | None = None
    config_snapshot: dict | None = None  # inline snapshot of the config at creation time


Rules:

Backwards-compatible defaults:

run_mode="queue", source="unknown", etc.

prompt_source:

"manual" when derived purely from prompt workspace.

"pack" when derived from a prompt pack entry.

config_snapshot:

For now, you can just do config_snapshot = config.to_dict() (or similar) when building the job.

If you already have any of these fields, align names/types instead of duplicating.

Note: This PR doesn’t fully plumb these fields through GUI; they’re filled in by PipelineController / JobService in a minimal, consistent way so we can use them later (e.g., Learning).

Step 2 – Build jobs with the metadata in PipelineController

File: src/controller/pipeline_controller.py

Find where PipelineController constructs jobs from:

current PipelineConfig,

any selected packs,

pipeline state.

Create a small helper, e.g.:

def _build_job(
    self,
    config: PipelineConfig,
    *,
    run_mode: str,
    source: str,
    prompt_source: str,
    prompt_pack_id: str | None = None,
) -> Job:
    run_mode = (run_mode or "queue").lower()
    if run_mode not in ("direct", "queue"):
        run_mode = "queue"

    snapshot = getattr(config, "to_dict", None)
    config_snapshot = snapshot() if callable(snapshot) else None

    return Job(
        job_id=self._job_id_factory(),  # existing id generator
        created_at=self._time_provider.now(),  # or datetime.now()
        config=config,
        run_mode=run_mode,
        source=source,
        prompt_source=prompt_source,
        prompt_pack_id=prompt_pack_id,
        config_snapshot=config_snapshot,
    )


Then, when assembling jobs:

For a manual Run from prompt workspace (no packs):

job = self._build_job(
    config=config,
    run_mode=pipeline_state.run_mode,
    source="run",
    prompt_source="manual",
    prompt_pack_id=None,
)


For a Run Now from a Job Draft / pack:

job = self._build_job(
    config=config_for_entry,
    run_mode=pipeline_state.run_mode,
    source="run_now",
    prompt_source="pack",
    prompt_pack_id=entry.pack_id,
)


For Add to Queue:

job = self._build_job(
    config=config_for_entry,
    run_mode="queue",  # or pipeline_state.run_mode if you want to respect user setting
    source="add_to_queue",
    prompt_source="pack",
    prompt_pack_id=entry.pack_id,
)


The important part is: every codepath that constructs a Job now always fills in run_mode + source + prompt metadata + config_snapshot.

Step 3 – Add JobService APIs for direct vs queued runs

File: src/queue/job_service.py

If you currently have something like:

class JobService:
    def enqueue(self, job: Job) -> None:
        ...

    def run_now(self, job: Job) -> None:
        ...


Introduce two minimal, explicit entrypoints:

class JobService:
    ...

    def submit_direct(self, job: Job) -> Job:
        """
        Run a job immediately (synchronous), record it in history.
        Does NOT enqueue the job.
        """
        job_id = job.job_id
        self._history.record_created(job)
        self._runner.run_once(job)  # new helper on SingleNodeJobRunner, see below
        self._history.record_completed(job_id)
        return job

    def submit_queued(self, job: Job) -> Job:
        """
        Enqueue a job and return it.
        Actual execution is handled asynchronously by SingleNodeJobRunner.
        """
        self._history.record_created(job)
        self._queue.enqueue(job)
        return job


If you already have run_now(job) vs enqueue(job) split, you can:

Keep them as they are.

Add tiny wrappers and move history responsibilities into these wrappers so PipelineController always uses submit_* and doesn’t scatter history logic.

Key point: Direct uses submit_direct, Queue uses submit_queued. Both record history; only the mode of execution differs.

Step 4 – Teach SingleNodeJobRunner how to do “run_once(job)”

File: src/queue/single_node_job_runner.py

If your runner currently pulls from the queue only, e.g.:

class SingleNodeJobRunner:
    def run_forever(self):
        while True:
            job = self._queue.pop()
            self._run_job(job)


Add a tiny synchronous helper:

class SingleNodeJobRunner:
    ...

    def run_once(self, job: Job) -> None:
        """
        Run a single job synchronously, using the same internal logic as queue-driven execution,
        but without touching the queue.
        """
        self._run_job(job)  # existing internal method


This reuses all existing plumbing for:

PipelineRunner invocation,

logging,

error handling,

but simply doesn’t involve the queue.

You don’t change run_forever(); you just give JobService a way to execute a job immediately.

Step 5 – Enforce run_mode in PipelineController when submitting jobs

File: src/controller/pipeline_controller.py

Right now (after previous PRs), you probably have something like:

for job in jobs:
    self.job_service.submit_job_with_run_mode(job)


We’re making it more explicit:

for job in jobs:
    mode = (job.run_mode or "queue").lower()
    if mode == "direct":
        self.job_service.submit_direct(job)
    else:
        self.job_service.submit_queued(job)


Or, if you prefer, keep submit_job_with_run_mode but implement it with this exact logic using the new APIs.

At this point:

PipelineController enforces that:

run_mode="direct" → synchronous execution via submit_direct.

run_mode="queue" → enqueued via submit_queued.

Tests
1. New: tests/pipeline/test_run_modes.py

Create a small focused module that tests the end-to-end decision:

Use a fake JobService + SingleNodeJobRunner, or a narrow harness around PipelineController.

Example:

class DummyRunner:
    def __init__(self):
        self.run_once_jobs = []

    def run_once(self, job):
        self.run_once_jobs.append(job)


class DummyQueue:
    def __init__(self):
        self.enqueued_jobs = []

    def enqueue(self, job):
        self.enqueued_jobs.append(job)


Wire them into a JobService and PipelineController (using test helpers or monkeypatch), then:

Test 1 – Direct mode

Build a PipelineConfig and Job with run_mode="direct".

Call the controller method that submits jobs (e.g. pipeline_controller.submit_pipeline_run([job])).

Assert:

assert dummy_runner.run_once_jobs == [job]
assert dummy_queue.enqueued_jobs == []


Also assert the JobHistoryStore has one created+completed entry with run_mode="direct".

Test 2 – Queue mode

Same, but run_mode="queue".

Assert:

assert dummy_runner.run_once_jobs == []
assert dummy_queue.enqueued_jobs == [job]


Assert job history has run_mode="queue" and source appropriately set.

Test 3 – Metadata populated

For either direct or queue:

Assert:

assert job.source in ("run", "run_now", "add_to_queue")
assert job.prompt_source in ("manual", "pack")
assert job.config_snapshot is not None


You don’t have to assert exact values for config_snapshot in this PR; just that something was stored.

Acceptance Criteria

 Job model has source, prompt_source, prompt_pack_id, and config_snapshot (or config_snapshot_id) fields, with backwards-compatible defaults.

 PipelineController always populates run_mode, source, prompt_source, prompt_pack_id, and config_snapshot when creating jobs.

 JobService exposes:

submit_direct(job) → synchronous path using SingleNodeJobRunner.run_once(job) and recording history.

submit_queued(job) → enqueued path using queue.enqueue(job) and recording history.

 SingleNodeJobRunner has a run_once(job) helper that reuses the same internal job execution path as queue-driven runs.

 PipelineController enforces run_mode:

"direct" → submit_direct(job).

"queue" → submit_queued(job).

 New tests in tests/pipeline/test_run_modes.py verify:

Direct jobs go through run_once and not enqueue.

Queue jobs go through enqueue and not run_once.

Job metadata fields are populated.